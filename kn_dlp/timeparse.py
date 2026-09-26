"""'1:23' / '01:02:03.5' / '90' 形式の時刻を秒に変換する。"""
from __future__ import annotations
from .i18n import tr


def parse_timestamp(text: str | None) -> float | None:
    """空なら None。不正なら ValueError。"""
    if text is None or not text.strip():
        return None
    parts = text.strip().split(':')
    if len(parts) > 3:
        raise ValueError(tr('時刻の形式が不正です: {text}', text=text))
    total = 0.0
    for i, part in enumerate(parts):
        try:
            value = float(part)
        except ValueError:
            raise ValueError(tr('時刻の形式が不正です: {text}', text=text)) from None
        if value < 0 or (i > 0 and value >= 60):
            raise ValueError(tr('時刻の形式が不正です: {text}', text=text))
        total = total * 60 + value
    return total


def format_seconds(seconds: float | int | None) -> str:
    if seconds is None:
        return '--:--'
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
