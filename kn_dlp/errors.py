"""yt-dlp のエラー文を日本語の要約+対処に変換する。原文はログに残す。"""
from __future__ import annotations

import re
from .i18n import N_, tr

# (パターン, 要約, 対処)。上から順に最初の一致を使う。
_RULES: list[tuple[str, str, str]] = [
    (r'Sign in to confirm (your age|you.re not a bot)', N_('ログイン確認を求められました'),
     N_('「Cookie」でログイン済みのブラウザを選んで再実行してください')),
    (r'Private video|members-only|This video is available to this channel.s members', N_('非公開・メンバー限定の動画です'),
     N_('視聴権限のあるアカウントのブラウザ Cookie を指定してください')),
    (r'(could not|failed to) (copy|decrypt|find).*cookie|DPAPI|App-Bound', N_('ブラウザの Cookie を読めませんでした'),
     N_('Chrome/Edge は起動中だと読めないことがあり、新しい暗号化方式では読めません。Firefox を推奨します')),
    (r'This live event will begin|Premieres in|is_upcoming', N_('配信はまだ始まっていません'),
     N_('「ライブ/プレミア開始を待って録画」を有効にすると開始まで待機します')),
    (r'ffmpeg.*not (found|installed)|ffprobe.*not found|You have requested merging', N_('ffmpeg が見つかりません'),
     N_('設定画面で ffmpeg を導入またはパスを指定してください')),
    (r'Requested format is not available', N_('指定した形式が存在しません'), N_('画質を「最高」にするか、形式一覧から選び直してください')),
    (r'Unsupported URL', N_('対応していない URL です'), N_('URL が正しいか確認してください')),
    (r'video (is )?unavailable|This video has been removed|HTTP Error 404|does not exist', N_('動画が見つかりません'), N_('削除・地域制限・URL 誤りの可能性があります')),
    (r'HTTP Error 403|Forbidden', N_('アクセスが拒否されました (403)'),
     N_('yt-dlp を最新版に更新してください。改善しなければ Cookie の指定を試してください')),
    (r'HTTP Error 429|Too Many Requests', N_('アクセスが多すぎます (429)'), N_('時間を置くか、同時実行数を減らしてください')),
    (r'No supported JavaScript runtime|JS runtime|n challenge', N_('JavaScript ランタイムが必要です'),
     N_('deno か Node.js を導入してください(設定画面で検出状況を確認できます)')),
    (r'getaddrinfo|Name or service not known|timed out|Connection (reset|refused|aborted)|Unable to connect',
     N_('ネットワークに接続できません'), N_('接続を確認して再試行してください')),
    (r'No space left|Errno 28', N_('ディスクの空き容量が足りません'), N_('保存先を変えるか容量を空けてください')),
    (r'Permission denied|Errno 13', N_('保存先に書き込めません'), N_('保存先フォルダの権限や、ファイルが開かれていないか確認してください')),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), s, h) for p, s, h in _RULES]
_PREFIX = re.compile(r'^(ERROR:\s*)?(\[[^\]]+\]\s*)?([\w-]+:\s*)?')


def explain(message: str) -> tuple[str, str]:
    """(要約, 対処)。該当なしなら原文の先頭行と汎用の対処を返す。"""
    text = message or ''
    for pattern, summary, hint in _COMPILED:
        if pattern.search(text):
            return tr(summary), tr(hint)
    first = text.strip().splitlines()[0] if text.strip() else tr('不明なエラー')
    first = _PREFIX.sub('', first, count=1)
    return first[:200], tr('ログを確認してください。yt-dlp の更新で直ることがあります')
