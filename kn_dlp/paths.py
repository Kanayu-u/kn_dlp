"""アプリのデータ置き場と同梱物の場所を一箇所で決める。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def app_root() -> Path:
    """同梱物(vendor/)の基点。exe 化時は展開先、開発時はリポジトリ直下。"""
    if is_frozen():
        return Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """設定・履歴・更新済み yt-dlp の置き場。KN_DLP_DATA で差し替え可(テスト用)。"""
    override = os.environ.get('KN_DLP_DATA')
    if override:
        base = Path(override)
    elif os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / APP_NAME
    else:
        base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def bundled_ytdlp() -> Path:
    return app_root() / 'vendor' / 'yt-dlp.pyz'


def updated_ytdlp() -> Path:
    return data_dir() / 'yt-dlp' / 'yt-dlp.pyz'


def default_download_dir() -> Path:
    return Path.home() / 'Downloads'
