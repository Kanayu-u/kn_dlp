"""ジョブ指定(JSON 化できる dict)から YoutubeDL のオプションを組み立てる。

ワーカー内で呼ぶ(download_ranges は関数なので JSON では運べないため)。
yt_dlp を import しない純粋関数にしてあり、単体テストで検証できる。
"""
from __future__ import annotations

import math
import os
import re
from typing import Any

from .timeparse import parse_timestamp
from .i18n import N_, tr

QUALITY_PRESETS = ['best', '2160', '1440', '1080', '720', '480', '360']
CONTAINERS = ['auto', 'mp4', 'mkv', 'webm']
AUDIO_CODECS = ['best', 'mp3', 'm4a', 'opus', 'flac', 'wav']
COOKIE_BROWSERS = ['firefox', 'chrome', 'edge', 'brave', 'opera', 'vivaldi', 'chromium', 'whale']

DEFAULT_TEMPLATE = '%(title)s [%(id)s].%(ext)s'

# ファイル名の雛形(表示名は翻訳キー)
TEMPLATE_PRESETS: list[tuple[str, str]] = [
    (N_('タイトル [ID]'), DEFAULT_TEMPLATE),
    (N_('タイトルのみ'), '%(title)s.%(ext)s'),
    (N_('投稿日 タイトル'), '%(upload_date>%Y-%m-%d)s %(title)s [%(id)s].%(ext)s'),
    (N_('投稿者のフォルダ / タイトル'), '%(uploader)s/%(title)s [%(id)s].%(ext)s'),
    (N_('再生リストのフォルダ / 番号 タイトル'), '%(playlist)s/%(playlist_index)03d %(title)s.%(ext)s'),
]

JOB_DEFAULTS: dict[str, Any] = {
    'url': '',
    'mode': 'video',            # video | audio
    'quality': 'best',          # QUALITY_PRESETS | custom
    'format': '',               # quality=custom のときの format 文字列
    'container': 'auto',
    'audio_codec': 'mp3',
    'audio_quality': '0',       # 0(最良)〜10、または '192K'
    'out_dir': '',
    'template': DEFAULT_TEMPLATE,
    'playlist': False,          # 動画+プレイリスト URL のときプレイリスト全体を取るか
    # C: 範囲切り出し
    'range_start': '',
    'range_end': '',
    'precise_cut': False,
    # D: 字幕・チャプター・サムネ
    'subs': False,
    'sub_langs': 'ja,en',
    'auto_subs': False,
    'embed_subs': True,
    'chapters': True,
    'embed_thumbnail': False,
    'metadata': True,
    # H: ライブ待機
    'wait_live': False,
    'wait_retry_sec': 60,
    'live_from_start': False,
    # I: Cookie(保存しない。ジョブ実行時に都度ブラウザから読む)
    'cookies_browser': '',
    'cookies_profile': '',
    'cookies_file': '',
    # 実行環境
    'ffmpeg_location': '',
    'js_runtime': None,         # {'name': 'node', 'path': '...'} | None
    'rate_limit': '',           # '5M' など
    'plugin_pps': [],           # 有効な後処理プラグイン [{'name', 'when', 'args'}](実行直前に設定から入れる)
}

# 後処理プラグインを動かす時点(yt-dlp の --use-postprocessor の when のうち、GUI で選べるもの)
PP_WHEN = ('pre_process', 'before_dl', 'post_process', 'after_move', 'playlist')
_PP_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
_PP_RESERVED = {'when', 'key', 'downloader'}


class JobError(ValueError):
    """ジョブ指定の不備(ユーザーに見せる日本語メッセージ)。"""


def normalize_job(job: dict[str, Any]) -> dict[str, Any]:
    """既定値を補い、未知のキーを捨てる。"""
    merged = dict(JOB_DEFAULTS)
    merged.update({k: v for k, v in job.items() if k in JOB_DEFAULTS})
    return merged


def validate_job(job: dict[str, Any]) -> None:
    url = str(job.get('url') or '').strip()
    if not url:
        raise JobError(tr('URL が空です'))
    if not url.lower().startswith(('http://', 'https://')):
        raise JobError(tr('URL は http:// か https:// で始まる必要があります'))
    if job['mode'] not in ('video', 'audio'):
        raise JobError(tr('不明なモード: {mode}', mode=job['mode']))
    if job['quality'] not in QUALITY_PRESETS + ['custom']:
        raise JobError(tr('不明な画質: {quality}', quality=job['quality']))
    if job['quality'] == 'custom' and not str(job['format']).strip():
        raise JobError(tr('形式を個別指定する場合は format を選んでください'))
    if job['container'] not in CONTAINERS:
        raise JobError(tr('不明なコンテナ: {container}', container=job['container']))
    if job['audio_codec'] not in AUDIO_CODECS:
        raise JobError(tr('不明な音声形式: {audio_codec}', audio_codec=job['audio_codec']))
    template = str(job['template'] or '')
    if not template.strip():
        raise JobError(tr('ファイル名テンプレートが空です'))
    if os.path.isabs(template) or '..' in template.replace('\\', '/').split('/'):
        raise JobError(tr('ファイル名テンプレートに絶対パスや .. は使えません'))
    if job['cookies_browser'] and job['cookies_browser'] not in COOKIE_BROWSERS:
        raise JobError(tr('未対応のブラウザ: {cookies_browser}', cookies_browser=job['cookies_browser']))
    try:
        start = parse_timestamp(job['range_start'])
        end = parse_timestamp(job['range_end'])
    except ValueError as e:
        raise JobError(str(e)) from None
    if start is not None and end is not None and end <= start:
        raise JobError(tr('切り出しの終了は開始より後にしてください'))


def build_format(job: dict[str, Any]) -> tuple[str, list[str]]:
    """(format, format_sort) を返す。"""
    if job['quality'] == 'custom':
        return str(job['format']).strip(), []
    if job['mode'] == 'audio':
        return 'ba/b', []
    sort: list[str] = []
    if job['container'] == 'mp4':
        # README 推奨: mp4 に収まる組み合わせを優先して再エンコードを避ける
        sort = ['ext:mp4:m4a']
    if job['quality'] == 'best':
        return 'bv*+ba/b', sort
    h = int(job['quality'])
    return f'bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b', sort


def _range_callback(start: float | None, end: float | None):
    def ranges(info_dict, _ydl):
        duration = info_dict.get('duration')
        s = start or 0.0
        e = end if end is not None else (duration if duration else math.inf)
        return [{'start_time': s, 'end_time': e}]
    return ranges


def build_postprocessors(job: dict[str, Any]) -> list[dict[str, Any]]:
    pps: list[dict[str, Any]] = []
    audio = job['mode'] == 'audio'
    if audio:
        pps.append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': job['audio_codec'],
            'preferredquality': str(job['audio_quality']),
            'nopostoverwrites': False,
        })
    elif job['container'] in ('mp4', 'mkv', 'webm'):
        pps.append({'key': 'FFmpegVideoRemuxer', 'preferedformat': job['container']})
    if job['subs'] and job['embed_subs'] and not audio:
        pps.append({'key': 'FFmpegEmbedSubtitle', 'already_have_subtitle': False})
    if job['metadata'] or job['chapters']:
        pps.append({
            'key': 'FFmpegMetadata',
            'add_chapters': bool(job['chapters']),
            'add_metadata': bool(job['metadata']),
            'add_infojson': False,
        })
    if job['embed_thumbnail']:
        if audio and job['audio_codec'] in ('mp3', 'm4a', 'best'):
            # webp のままでは mp3/m4a に埋め込めないため jpg へ変換してから
            pps.insert(0, {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'})
        pps.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
    return pps


def parse_pp_args(text: str) -> dict[str, str]:
    """'key=value;key2=value2'(--use-postprocessor と同じ書式)を辞書にする。値は文字列のまま。"""
    args: dict[str, str] = {}
    for part in str(text or '').split(';'):
        if not part.strip():
            continue
        key, eq, value = part.partition('=')
        key = key.strip()
        if not eq or not _PP_NAME_RE.match(key):
            raise JobError(tr('後処理の引数は key=value を ; で区切って指定してください: {part}', part=part.strip()))
        if key in _PP_RESERVED:
            raise JobError(tr('後処理の引数に {key} は使えません', key=key))
        args[key] = value
    return args


def plugin_pp_spec(spec: Any) -> tuple[str, str, dict[str, str]]:
    """設定の1項目を (名前, 時点, 引数) に検証・変換する。"""
    if not isinstance(spec, dict):
        raise JobError(tr('後処理プラグインの指定が不正です'))
    name, when = str(spec.get('name') or ''), str(spec.get('when') or 'post_process')
    if not _PP_NAME_RE.match(name):
        raise JobError(tr('後処理プラグインの名前が不正です: {name}', name=name))
    if when not in PP_WHEN:
        raise JobError(tr('後処理プラグインの実行時点が不正です: {when}', when=when))
    return name, when, parse_pp_args(spec.get('args') or '')


def final_ext(job: dict[str, Any], ext: str | None) -> str | None:
    """変換・結合後の拡張子(プレビュー用)。決められなければ元のまま。"""
    job = normalize_job(job)
    if job['mode'] == 'audio':
        return job['audio_codec'] if job['audio_codec'] != 'best' else ext
    if job['container'] in ('mp4', 'mkv', 'webm'):
        return job['container']
    return ext


def _parse_rate(rate: str) -> int | None:
    rate = (rate or '').strip().upper().rstrip('B')
    if not rate:
        return None
    mult = {'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3}.get(rate[-1], 1)
    number = rate[:-1] if rate[-1] in 'KMG' else rate
    try:
        value = float(number)
    except ValueError:
        raise JobError(tr('速度制限の形式が不正です: {rate}', rate=rate)) from None
    if value <= 0:
        raise JobError(tr('速度制限は正の値にしてください'))
    return int(value * mult)


def build_ydl_opts(job: dict[str, Any], *, logger=None, progress_hooks=(), postprocessor_hooks=()) -> dict[str, Any]:
    job = normalize_job(job)
    validate_job(job)
    fmt, fmt_sort = build_format(job)
    template = str(job['template'])
    start = parse_timestamp(job['range_start'])
    end = parse_timestamp(job['range_end'])
    ranged = start is not None or end is not None
    if ranged and '%(section_start' not in template:
        root, dot, ext = template.rpartition('.')
        template = f'{root} [%(section_start)d-%(section_end)d].{ext}' if dot else template

    opts: dict[str, Any] = {
        'format': fmt,
        'paths': {'home': job['out_dir'] or os.getcwd()},
        'outtmpl': {'default': template},
        'noplaylist': not job['playlist'],
        'extract_flat': False,
        'continuedl': True,
        'nopart': False,
        'quiet': True,
        'no_warnings': False,
        'noprogress': True,
        'color': {'stdout': 'never', 'stderr': 'never'},
        'windowsfilenames': os.name == 'nt',
        'postprocessors': build_postprocessors(job),
        'progress_hooks': list(progress_hooks),
        'postprocessor_hooks': list(postprocessor_hooks),
        'retries': 10,
        'fragment_retries': 10,
    }
    if fmt_sort:
        opts['format_sort'] = fmt_sort
    if job['mode'] == 'video' and job['container'] in ('mp4', 'mkv', 'webm'):
        opts['merge_output_format'] = job['container']
    if logger is not None:
        opts['logger'] = logger
    if ranged:
        opts['download_ranges'] = _range_callback(start, end)
        opts['force_keyframes_at_cuts'] = bool(job['precise_cut'])
    if job['subs']:
        opts['writesubtitles'] = True
        opts['writeautomaticsub'] = bool(job['auto_subs'])
        langs = [s.strip() for s in str(job['sub_langs']).split(',') if s.strip()]
        opts['subtitleslangs'] = langs or ['all']
    if job['embed_thumbnail']:
        opts['writethumbnail'] = True
    if job['wait_live']:
        retry = max(15, int(job['wait_retry_sec'] or 60))
        opts['wait_for_video'] = (retry, retry)
    if job['live_from_start']:
        opts['live_from_start'] = True
    if job['cookies_file']:
        opts['cookiefile'] = job['cookies_file']
    elif job['cookies_browser']:
        opts['cookiesfrombrowser'] = (job['cookies_browser'], job['cookies_profile'] or None, None, None)
    if job['ffmpeg_location']:
        opts['ffmpeg_location'] = job['ffmpeg_location']
    rt = job['js_runtime']
    if rt and rt.get('name'):
        opts['js_runtimes'] = {rt['name']: ({'path': rt['path']} if rt.get('path') else {})}
    if (rate := _parse_rate(job['rate_limit'])) is not None:
        opts['ratelimit'] = rate
    return opts


def build_probe_opts(job: dict[str, Any], *, logger=None) -> dict[str, Any]:
    """解析(メタデータ取得)用。プレイリストは中身を展開しない。"""
    opts = build_ydl_opts(job, logger=logger)
    for key in ('postprocessors', 'download_ranges', 'writesubtitles', 'writethumbnail', 'wait_for_video'):
        opts.pop(key, None)
    opts.update({'skip_download': True, 'extract_flat': 'in_playlist', 'noplaylist': not job.get('playlist'),
                 # 配信予定のライブは形式が無い。エラーにせず情報(live_status=is_upcoming)を返させる
                 'ignore_no_formats_error': True})
    return opts
