"""yt-dlp 本体の選択と読み込み。

更新可能にするため、yt-dlp は exe に焼き込まず公式 zipapp(yt-dlp.pyz)として置く。
同梱版と更新版のうち新しい方を sys.path の先頭に差し込んでから import する。
GUI プロセスは yt_dlp を import しない(ワーカーだけが読む)ので、更新は再起動なしで次のジョブから効く。
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from . import paths

_VERSION_RE = re.compile(r"""__version__\s*=\s*['"]([^'"]+)['"]""")


def read_pyz_version(pyz: Path) -> str | None:
    """zipapp を import せずに版番号を読む。壊れていれば None。"""
    try:
        with zipfile.ZipFile(pyz) as zf:
            src = zf.read('yt_dlp/version.py').decode('utf-8', 'replace')
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    m = _VERSION_RE.search(src)
    return m.group(1) if m else None


def version_key(version: str) -> tuple[int, ...]:
    """'2026.08.19' や '2026.08.19.232826'(nightly) を比較可能にする。"""
    return tuple(int(p) for p in re.findall(r'\d+', version))


def select_pyz() -> tuple[Path, str] | None:
    """使うべき zipapp と版。どちらも無ければ None(開発時は site-packages にフォールバック)。"""
    candidates = []
    for pyz in (paths.updated_ytdlp(), paths.bundled_ytdlp()):
        if pyz.is_file() and (ver := read_pyz_version(pyz)):
            candidates.append((version_key(ver), pyz, ver))
    if not candidates:
        return None
    _, pyz, ver = max(candidates, key=lambda c: c[0])
    return pyz, ver


def activate() -> str:
    """ワーカー起動時に1回呼ぶ。読み込んだ yt-dlp の出所を返す。"""
    if 'yt_dlp' in sys.modules:
        return 'already-imported'
    chosen = select_pyz()
    if chosen:
        sys.path.insert(0, str(chosen[0]))
        return str(chosen[0])
    return 'site-packages'
