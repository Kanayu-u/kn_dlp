"""yt-dlp を実行する子プロセス。

GUI とは 1 行 1 JSON でやり取りする。
  stdin : {"action": "probe" | "download" | "version" | "plugins" | "match", "job": {...}}  (1 行)
  stdout: {"t": "log" | "meta" | "progress" | "stage" | "file" | "result" | "error", ...}
yt-dlp や ffmpeg が標準出力に書いてもプロトコルが壊れないよう、fd 1 は起動直後に stderr へ付け替える。
キャンセル・一時停止は GUI がこのプロセスをツリーごと終了させる(.part は残るので再開できる)。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import traceback
from typing import Any
from .i18n import tr

_proto: io.TextIOBase | None = None


def emit(msg_type: str, /, **payload: Any) -> None:
    if _proto is None:
        return
    payload['t'] = msg_type
    try:
        _proto.write(json.dumps(payload, ensure_ascii=False, default=str) + '\n')
        _proto.flush()
    except (OSError, ValueError):
        os._exit(3)  # GUI 側が閉じた


class _Logger:
    def debug(self, msg: str) -> None:
        if msg.startswith('[debug] '):
            return
        emit('log', level='info', msg=msg)

    def info(self, msg: str) -> None:
        emit('log', level='info', msg=msg)

    def warning(self, msg: str) -> None:
        emit('log', level='warning', msg=msg)

    def error(self, msg: str) -> None:
        emit('log', level='error', msg=msg)


def _setup_stdio() -> None:
    global _proto
    _proto = os.fdopen(os.dup(1), 'w', encoding='utf-8', newline='\n', buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr


def _detach_stdin() -> None:
    """要求を読んだ後、子プロセス(ffmpeg)へ引き継がれる標準ハンドルを確実に有効な値へ揃える。

    exe 版を CREATE_NO_WINDOW で起動すると、Win32 側の標準ハンドル(GetStdHandle)が CRT の fd と
    食い違ったまま残り、ffmpeg 起動時に [WinError 6] になる。fd 0 を NUL に差し替え、
    SetStdHandle で 0/1/2 を CRT の実体へ合わせる。
    """
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    if os.name != 'nt':
        return
    try:
        import ctypes
        import msvcrt
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.SetStdHandle.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        for fd, std in ((0, -10), (1, -11), (2, -12)):   # STD_INPUT/OUTPUT/ERROR_HANDLE
            kernel32.SetStdHandle(ctypes.c_uint32(std & 0xFFFFFFFF), msvcrt.get_osfhandle(fd))
    except (OSError, AttributeError):
        pass


def _trim_format(f: dict) -> dict:
    keys = ('format_id', 'ext', 'resolution', 'height', 'width', 'fps', 'vcodec', 'acodec', 'abr', 'tbr',
            'filesize', 'filesize_approx', 'format_note', 'protocol', 'dynamic_range', 'language')
    return {k: f.get(k) for k in keys if f.get(k) is not None}


def _trim_info(info: dict) -> dict:
    out = {k: info.get(k) for k in (
        'id', 'title', 'uploader', 'channel', 'duration', 'thumbnail', 'webpage_url', 'extractor_key',
        'is_live', 'live_status', 'release_timestamp', '_type', 'playlist_count', 'upload_date', 'view_count')}
    if not out['thumbnail'] and info.get('thumbnails'):
        out['thumbnail'] = info['thumbnails'][-1].get('url')
    out['formats'] = [_trim_format(f) for f in info.get('formats') or []]
    out['subtitles'] = sorted((info.get('subtitles') or {}).keys())
    out['auto_captions'] = sorted((info.get('automatic_captions') or {}).keys())
    out['chapters'] = len(info.get('chapters') or [])
    if info.get('_type') == 'playlist':
        entries = []
        for e in info.get('entries') or []:
            if len(entries) >= 500:
                break
            if e:
                entries.append({'title': e.get('title'), 'url': e.get('url') or e.get('webpage_url'),
                                'duration': e.get('duration')})
        out['entries'] = entries
        out['playlist_count'] = info.get('playlist_count') or len(entries)
    return out


class _Progress:
    """progress_hooks 用。GUI を詰まらせないよう 0.25 秒に 1 回へ間引く。"""

    def __init__(self) -> None:
        self.last = 0.0
        self.seen: set[str] = set()

    def hook(self, d: dict) -> None:
        info = d.get('info_dict') or {}
        vid = str(info.get('id') or '')
        if vid and vid not in self.seen:
            self.seen.add(vid)
            emit('meta', id=vid, title=info.get('title'), uploader=info.get('uploader') or info.get('channel'),
                 extractor=info.get('extractor_key'), playlist_index=info.get('playlist_index'),
                 n_entries=info.get('n_entries'), is_live=info.get('is_live'))
        status = d.get('status')
        now = time.monotonic()
        if status == 'downloading':
            if now - self.last < 0.25:
                return
            self.last = now
            emit('progress', downloaded=d.get('downloaded_bytes'),
                 total=d.get('total_bytes') or d.get('total_bytes_estimate'), speed=d.get('speed'),
                 eta=d.get('eta'), frag=d.get('fragment_index'), frags=d.get('fragment_count'),
                 elapsed=d.get('elapsed'), filename=d.get('filename') or '')
        elif status == 'finished':
            self.last = 0.0
            emit('progress', downloaded=d.get('total_bytes') or d.get('downloaded_bytes'),
                 total=d.get('total_bytes') or d.get('downloaded_bytes'), speed=None, eta=0, done=True,
                 filename=d.get('filename') or '')

    def pp_hook(self, d: dict) -> None:
        if d.get('status') == 'started':
            emit('stage', name=d.get('postprocessor'))


def _run(request: dict) -> int:
    from . import bootstrap
    source = bootstrap.activate()
    import yt_dlp  # noqa: E402  (bootstrap 後に読む)
    from yt_dlp.version import __version__ as ytdlp_version

    from .options import JobError, build_probe_opts, build_ydl_opts

    action = request.get('action')
    if action == 'version':
        emit('result', version=ytdlp_version, source=source)
        return 0

    from . import plugins
    load_errors = plugins.activate()
    if action == 'plugins':
        emit('result', mode=plugins.env_mode(), errors=load_errors, **plugins.list_loaded())
        return 0
    if action == 'match':
        url = str((request.get('job') or {}).get('url') or '').strip()
        emit('result', url=url, matches=plugins.match_url(url) if url else [], errors=load_errors)
        return 0

    job = request.get('job') or {}
    logger = _Logger()
    for err in load_errors:
        logger.warning(tr('プラグインを読み込めませんでした: {module}: {error}', **err))
    ffmpeg = str(job.get('ffmpeg_location') or '')
    if ffmpeg:
        # 範囲DLの事前チェック(FFmpegFD.available)は params を見ず contextvar だけを見る。
        # CLI は __init__ で設定しているが、ライブラリ利用では自前で設定しないと「ffmpeg 未導入」扱いになる。
        from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
        FFmpegPostProcessor._ffmpeg_location.set(ffmpeg)
        ff_dir = ffmpeg if os.path.isdir(ffmpeg) else os.path.dirname(ffmpeg)
        os.environ['PATH'] = ff_dir + os.pathsep + os.environ.get('PATH', '')
    try:
        if action == 'probe':
            opts = build_probe_opts(job, logger=logger)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(job['url'], download=False)
                _note_plugin(ydl, info or {}, logger, set())
                info = ydl.sanitize_info(info)
            emit('result', info=_trim_info(info or {}), ytdlp=ytdlp_version)
            return 0
        if action == 'download':
            progress = _Progress()
            opts = build_ydl_opts(job, logger=logger, progress_hooks=[progress.hook],
                                  postprocessor_hooks=[progress.pp_hook])
            opts['post_hooks'] = [lambda path: emit('file', path=path, size=_size(path))]
            embed_args = _pop_postprocessor(opts, 'EmbedThumbnail')
            with yt_dlp.YoutubeDL(opts) as ydl:
                if embed_args is not None:
                    ydl.add_post_processor(_safe_embed_thumbnail(ydl, embed_args), when='post_process')
                ydl.add_post_processor(_plugin_notice(ydl, logger), when='pre_process')
                _add_plugin_pps(ydl, job.get('plugin_pps') or [], logger)
                code = ydl.download([job['url']])
            emit('result', code=code, ytdlp=ytdlp_version)
            return 0 if code == 0 else 1
        emit('error', msg=f'unknown action: {action}')
        return 2
    except JobError as e:
        emit('error', msg=str(e), kind='job')
        return 2
    except yt_dlp.utils.DownloadError as e:
        emit('error', msg=str(e), kind='download')
        return 1
    except Exception as e:  # noqa: BLE001
        emit('error', msg=f'{type(e).__name__}: {e}', kind='internal', trace=traceback.format_exc())
        return 1


def _pop_postprocessor(opts: dict, key: str) -> dict | None:
    """opts['postprocessors'] から key の定義を抜き出し、引数を返す。無ければ None。"""
    pps = opts.get('postprocessors') or []
    for i, pp in enumerate(pps):
        if pp.get('key') == key:
            args = {k: v for k, v in pps.pop(i).items() if k not in ('key', 'when')}
            return args
    return None


def _safe_embed_thumbnail(ydl, args: dict):
    """埋め込めない形式(webm / wav、mutagen 無しの opus / flac / ogg)では失敗させずに飛ばす。

    標準の EmbedThumbnail は例外を投げ、ダウンロード済みでもジョブ全体が失敗扱いになる。
    飛ばした場合、サムネイルは画像ファイルとして動画の横に残る。
    """
    from yt_dlp.postprocessor import embedthumbnail as mod

    ffmpeg_exts = {'mp3', 'mkv', 'mka', 'm4a', 'mp4', 'm4v', 'mov'}
    mutagen_exts = {'ogg', 'opus', 'flac'}

    class EmbedThumbnailPP(mod.EmbedThumbnailPP):   # クラス名が PP 名(段階表示)になるので同名にする
        def run(self, info):
            ext = info.get('ext')
            if ext in ffmpeg_exts or (ext in mutagen_exts and mod.mutagen):
                return super().run(info)
            self.report_warning(tr('{ext} にはサムネイルを埋め込めないため、画像ファイルとして残しました', ext=ext))
            return [], info

    return EmbedThumbnailPP(ydl, **args)


def _note_plugin(ydl, info: dict, logger: _Logger, seen: set[str]) -> None:
    """プラグインの抽出器が使われたら、その名前をログに出す(同じものは1回だけ)。"""
    from . import plugins
    key = info.get('extractor_key')
    if not key or key in seen:
        return
    seen.add(key)
    try:
        ie = ydl.get_info_extractor(key)
    except Exception:  # noqa: BLE001  (取れなくてもダウンロードは続ける)
        return
    if plugins.is_plugin_extractor(ie):
        logger.info(tr('プラグインを使用: {name}', name=getattr(ie, 'IE_NAME', key)))


def _add_plugin_pps(ydl, specs: list, logger: _Logger) -> None:
    """有効にした後処理プラグインを、標準の後処理の後ろに足す。

    params['postprocessors'] に入れると埋め込み等より前に走ってしまう(更新日時を揃える PP などが無意味になる)ので、
    YoutubeDL 生成後に add_post_processor で末尾へ追加する。無い・引数が合わないものは警告して飛ばす。
    """
    from yt_dlp.globals import plugin_pps
    from .options import JobError, plugin_pp_spec

    for spec in specs:
        try:
            name, when, args = plugin_pp_spec(spec)
        except JobError as e:
            logger.warning(str(e))
            continue
        cls = plugin_pps.value.get(f'{name}PP')
        if cls is None:
            logger.warning(tr('後処理プラグイン {name} が見つからないため飛ばしました', name=name))
            continue
        try:
            pp = cls(ydl, **args)
        except Exception as e:  # noqa: BLE001  (プラグインの不備でジョブ全体を落とさない)
            logger.warning(tr('後処理プラグイン {name} を開始できませんでした: {error}', name=name, error=f'{type(e).__name__}: {e}'))
            continue
        ydl.add_post_processor(pp, when=when)
        logger.info(tr('後処理プラグインを追加: {name} ({when})', name=name, when=when))


def _plugin_notice(ydl, logger: _Logger):
    """ダウンロード前(pre_process)に、使われた抽出器を確認するだけの後処理。"""
    from yt_dlp.postprocessor.common import PostProcessor

    seen: set[str] = set()

    class PluginNoticePP(PostProcessor):
        def set_downloader(self, downloader):
            self._downloader = downloader   # 進捗フックは付けない(段階表示に出さない)

        def run(self, info):
            _note_plugin(ydl, info, logger, seen)
            return [], info

    return PluginNoticePP(ydl)


def _size(path: str) -> int | None:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def main() -> int:
    _setup_stdio()
    from . import i18n
    i18n.set_language(os.environ.get('KN_DLP_LANG') or None)
    line = sys.stdin.readline() if sys.stdin else ''
    try:
        request = json.loads(line)
        if not isinstance(request, dict):
            raise ValueError('request must be an object')
    except ValueError as e:
        emit('error', msg=f'bad request: {e}', kind='internal')
        return 2
    _detach_stdin()
    return _run(request)
