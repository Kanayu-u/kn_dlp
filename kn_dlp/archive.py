"""ダウンロード済みの記録(yt-dlp の download archive)。1 行 = 「抽出器名 動画ID」。"""
from __future__ import annotations

import os
from pathlib import Path

from . import paths


def path() -> Path:
    return paths.data_dir() / 'archive.txt'


def count() -> int:
    try:
        with open(path(), encoding='utf-8', errors='replace') as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def clear() -> None:
    """記録を消す。誤操作に備えて直前の1世代を .bak に残す。"""
    p = path()
    if p.exists():
        os.replace(p, p.with_name(p.name + '.bak'))
