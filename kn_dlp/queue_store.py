"""終わっていないキューの保存と復元。JSON 1ファイル、書き込みは一時ファイル経由で原子的に。"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from . import paths

VERSION = 1
KEEP_STATUSES = ('queued', 'scheduled', 'paused', 'running')
# 実行直前に入れ直す実行環境。保存しない
RUNTIME_KEYS = ('ffmpeg_location', 'js_runtime', 'plugin_pps', 'archive_file')
MAX_JOBS = 1000


def path() -> Path:
    return paths.data_dir() / 'queue.json'


def save(items: list[dict[str, Any]]) -> None:
    p = path()
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix='.queue-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump({'version': VERSION, 'jobs': items}, f, ensure_ascii=False)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load() -> list[dict[str, Any]]:
    """壊れた項目は捨てて返す。ファイルが無い・壊れているときは空。"""
    try:
        raw = json.loads(path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict) or raw.get('version') != VERSION or not isinstance(raw.get('jobs'), list):
        return []
    out = []
    for it in raw['jobs'][:MAX_JOBS]:
        if not isinstance(it, dict) or not isinstance(it.get('spec'), dict) or it.get('status') not in KEEP_STATUSES:
            continue
        spec = {k: v for k, v in it['spec'].items() if k not in RUNTIME_KEYS}
        if not isinstance(spec.get('url'), str) or not spec['url']:
            continue
        start_at = it.get('start_at')
        out.append({
            'spec': spec,
            'title': it['title'] if isinstance(it.get('title'), str) else spec['url'],
            'thumbnail': it['thumbnail'] if isinstance(it.get('thumbnail'), str) else '',
            'start_at': float(start_at) if isinstance(start_at, (int, float)) and not isinstance(start_at, bool) else None,
            'status': it['status'],
            'partials': [p for p in it.get('partials') or [] if isinstance(p, str)],
        })
    return out
