"""UI の多言語化。日本語の原文をそのままキーにする(gettext と同じ考え方)。

- `tr('原文 {name}', name=...)`: 現在の言語へ翻訳して format する。訳が無ければ原文を使う
- `N_('原文')`: 翻訳対象の印だけ付ける(モジュール読み込み時に評価される定数用)。表示時に tr() を通す
言語の切り替えは再起動で反映する(画面は起動時の言語で組み立てる)。
"""
from __future__ import annotations

import locale
import os

LANG_NAMES = {'ja': '日本語', 'en': 'English', 'ko': '한국어', 'zh_CN': '简体中文'}
DEFAULT = 'en'

_table: dict[str, str] = {}
_current = 'ja'


def N_(text: str) -> str:
    return text


def tr(text: str, /, **kwargs) -> str:
    s = _table.get(text, text)
    if not kwargs:
        return s
    try:
        return s.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text.format(**kwargs)   # 訳の置換欄が壊れていても原文で表示を続ける


def normalize(code: str | None) -> str:
    """'ja_JP' / 'zh-Hans-CN' / 'ko-KR' などを対応言語のコードへ。未対応は英語。"""
    c = (code or '').replace('-', '_').lower()
    if c.startswith('ja'):
        return 'ja'
    if c.startswith('ko'):
        return 'ko'
    if c.startswith('zh'):
        return 'zh_CN'
    if c.startswith('en'):
        return 'en'
    return DEFAULT


def system_language() -> str:
    if os.name == 'nt':
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return normalize(locale.windows_locale.get(lcid, ''))
        except (OSError, AttributeError):
            pass
    try:
        return normalize(locale.getlocale()[0] or os.environ.get('LANG', ''))
    except ValueError:
        return DEFAULT


def _load(code: str) -> dict[str, str]:
    # PyInstaller が拾えるよう、動的 import ではなく静的に書く
    if code == 'en':
        from . import en
        return en.T
    if code == 'ko':
        from . import ko
        return ko.T
    if code == 'zh_CN':
        from . import zh_CN
        return zh_CN.T
    return {}


def set_language(code: str | None) -> str:
    """'' / None は OS の言語。実際に使う言語コードを返す。"""
    global _table, _current
    _current = normalize(code) if code else system_language()
    _table = _load(_current)
    return _current


def current() -> str:
    return _current
