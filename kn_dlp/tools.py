"""外部ツール(ffmpeg / JS ランタイム)の検出。見つからなくても例外にしない。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import paths

JS_RUNTIME_ORDER = ['deno', 'node', 'bun']


def _exe(name: str) -> str:
    return f'{name}.exe' if os.name == 'nt' else name


def _extra_dirs(name: str) -> list[Path]:
    home = Path.home()
    dirs = [paths.app_root() / 'vendor' / 'ffmpeg' / 'bin', paths.data_dir() / 'ffmpeg' / 'bin']
    local = os.environ.get('LOCALAPPDATA')
    if local:
        # winget は PATH を新しいプロセスにしか反映しないので Links を直接見る
        dirs.append(Path(local) / 'Microsoft' / 'WinGet' / 'Links')
    if name == 'deno':
        dirs.append(home / '.deno' / 'bin')
    if name == 'bun':
        dirs.append(home / '.bun' / 'bin')
    return dirs


def find_tool(name: str, override: str = '') -> str | None:
    if override:
        p = Path(override)
        if p.is_dir():
            p = p / _exe(name)
        return str(p) if p.is_file() else None
    found = shutil.which(name)
    if found:
        return found
    for d in _extra_dirs(name):
        candidate = d / _exe(name)
        if candidate.is_file():
            return str(candidate)
    return None


def find_ffmpeg(override: str = '') -> str | None:
    """ffmpeg.exe のパス。yt-dlp にはその親ディレクトリを渡す(ffprobe も同じ場所にある前提)。"""
    return find_tool('ffmpeg', override)


def find_js_runtime(preferred: str = '') -> dict | None:
    order = [preferred] + [n for n in JS_RUNTIME_ORDER if n != preferred] if preferred else JS_RUNTIME_ORDER
    for name in order:
        path = find_tool(name)
        if path:
            return {'name': name, 'path': path}
    return None
