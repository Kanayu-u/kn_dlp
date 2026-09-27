"""ダウンロード履歴(E)。SQLite。GUI スレッドからのみ使う。"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    title       TEXT,
    uploader    TEXT,
    extractor   TEXT,
    filepath    TEXT,
    filesize    INTEGER,
    status      TEXT NOT NULL,          -- done | error | cancelled
    error       TEXT,
    job_json    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_downloads_created ON downloads(created_at DESC);
"""

# 履歴に残すジョブ項目から除く(Cookie の指定元や実行環境は再ダウンロード時に現在の設定を使う)
_EXCLUDE_FROM_JOB = {'cookies_file', 'cookies_profile', 'ffmpeg_location', 'js_runtime', 'plugin_pps', 'archive_file'}


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.data_dir() / 'history.sqlite3'
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def add(self, job: dict[str, Any], *, status: str, title: str = '', uploader: str = '', extractor: str = '',
            filepath: str = '', filesize: int | None = None, error: str = '', created_at: float | None = None) -> int:
        stored = {k: v for k, v in job.items() if k not in _EXCLUDE_FROM_JOB}
        cur = self.conn.execute(
            'INSERT INTO downloads (url, title, uploader, extractor, filepath, filesize, status, error, job_json,'
            ' created_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (job.get('url', ''), title, uploader, extractor, filepath, filesize, status, error,
             json.dumps(stored, ensure_ascii=False), created_at or time.time(), time.time()))
        self.conn.commit()
        return int(cur.lastrowid)

    def search(self, text: str = '', limit: int = 500) -> list[dict[str, Any]]:
        sql = 'SELECT * FROM downloads'
        args: list[Any] = []
        if text.strip():
            like = '%' + text.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            sql += " WHERE title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\' OR uploader LIKE ? ESCAPE '\\'"
            args += [like, like, like]
        sql += ' ORDER BY created_at DESC LIMIT ?'
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args)]

    def get(self, row_id: int) -> dict[str, Any] | None:
        row = self.conn.execute('SELECT * FROM downloads WHERE id = ?', (row_id,)).fetchone()
        return dict(row) if row else None

    def job_of(self, row_id: int) -> dict[str, Any] | None:
        row = self.get(row_id)
        if not row:
            return None
        try:
            job = json.loads(row['job_json'])
        except ValueError:
            return None
        return job if isinstance(job, dict) else None

    def delete(self, row_ids: list[int]) -> None:
        self.conn.executemany('DELETE FROM downloads WHERE id = ?', [(i,) for i in row_ids])
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute('DELETE FROM downloads')
        self.conn.commit()
