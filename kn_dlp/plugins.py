"""yt-dlp プラグインの読み込み範囲と一覧。

プラグインは yt-dlp 公式の仕組み(yt_dlp_plugins 名前空間パッケージ)をそのまま使う。
kn_dlp 専用フォルダ(データフォルダ/plugins)と、yt-dlp 本体の既定の場所(%APPDATA%/yt-dlp/plugins 等)から読む。
読み込み範囲は GUI の設定を環境変数 KN_DLP_PLUGINS でワーカーへ渡す。yt_dlp を import するのはワーカーだけ。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import re
import sys
from pathlib import Path
from typing import Any

from . import paths

MODES = ('all', 'app', 'off')   # すべて / kn_dlp のみ / オフ
ENV_KEY = 'KN_DLP_PLUGINS'
PACKAGE = 'yt_dlp_plugins'

_mode = 'all'

README = """\
kn_dlp plugins folder / プラグインフォルダ

Put yt-dlp plugins here. Each plugin is a package folder (or a .zip) laid out like this:
yt-dlp のプラグインをここに置きます。1つのプラグインは次の形のフォルダ(または .zip)です。

  plugins\\
    <any-name>\\
      yt_dlp_plugins\\
        extractor\\<name>.py        site support / サイト対応
        postprocessor\\<name>.py    post-processing / 後処理

Plugins run as Python code with your user rights. Only install plugins you trust.
プラグインはあなたの権限で動く Python コードです。信頼できるものだけを置いてください。

Docs: https://github.com/yt-dlp/yt-dlp#plugins
"""


# ---- GUI 側(プロセス全体の設定値。言語と同じく、ワーカー起動時に環境変数で渡す) ----
def set_mode(mode: str) -> str:
    global _mode
    _mode = mode if mode in MODES else 'all'
    return _mode


def current_mode() -> str:
    return _mode


def plugins_dir() -> Path:
    return paths.data_dir() / 'plugins'


def ensure_dir() -> Path | None:
    """専用フォルダと説明書きを用意する。作れなければ None。"""
    d = plugins_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        readme = d / 'README.txt'
        if not readme.exists():
            readme.write_text(README, encoding='utf-8')
    except OSError:
        return None
    return d


def search_dirs(mode: str) -> list[str]:
    """yt_dlp.globals.plugin_dirs に入れる値。'default' は yt-dlp 本体の既定の探索場所を表す。"""
    if mode == 'off':
        return []
    d = ensure_dir()
    own = [str(d)] if d else []
    return own if mode == 'app' else own + ['default']


# ---- ワーカー側 ----
_ERR_RE = re.compile(r"Error while importing module '([^']+)'")


def parse_errors(text: str) -> list[dict[str, str]]:
    """yt-dlp が stderr に書く読み込みエラーを、モジュール名と最終行(例外)に分ける。"""
    errors = []
    parts = _ERR_RE.split(text)
    for module, body in zip(parts[1::2], parts[2::2]):
        lines = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
        errors.append({'module': module, 'error': lines[-1] if lines else ''})
    return errors


def env_mode() -> str:
    mode = os.environ.get(ENV_KEY, 'all')
    return mode if mode in MODES else 'all'


def activate(mode: str | None = None) -> list[dict[str, str]]:
    """読み込み範囲を設定してプラグインを読み込み、読み込みエラーを返す。YoutubeDL を作る前に1回呼ぶ。"""
    mode = mode if mode in MODES else env_mode()
    from yt_dlp.globals import plugin_dirs
    from yt_dlp.plugins import load_all_plugins
    plugin_dirs.value = search_dirs(mode)
    if mode == 'off':
        os.environ['YTDLP_NO_PLUGINS'] = '1'    # yt-dlp 側の無効化スイッチも併用する
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        load_all_plugins()
    return parse_errors(buf.getvalue())


def _source_file(cls: type) -> str:
    try:
        return inspect.getfile(cls)
    except (TypeError, OSError):
        return getattr(sys.modules.get(cls.__module__), '__file__', '') or ''


def list_loaded() -> dict[str, Any]:
    """activate() 後に、読み込まれたプラグインと探索場所を返す。"""
    from yt_dlp.globals import plugin_ies, plugin_ies_overrides, plugin_pps
    from yt_dlp.plugins import directories
    items = []
    for kind, lookup in (('extractor', plugin_ies.value), ('postprocessor', plugin_pps.value)):
        for name, cls in sorted(lookup.items()):
            items.append({'kind': kind, 'name': getattr(cls, 'IE_NAME', None) or name,
                          'class': name, 'file': _source_file(cls)})
    for parent, overrides in plugin_ies_overrides.value.items():
        for cls in overrides:
            items.append({'kind': 'override', 'name': getattr(parent, 'IE_NAME', parent.__name__),
                          'class': cls.__name__, 'file': _source_file(cls)})
    return {'items': items, 'dirs': directories()}


def is_plugin_extractor(ie: Any) -> bool:
    """実際に使われた抽出器がプラグイン由来(上書きを含む)か。"""
    cls = type(ie)
    return cls.__module__.startswith(PACKAGE) or '+' in str(getattr(ie, 'IE_NAME', ''))
