"""ダウンロードキュー。同時実行数・予約開始(H)・一時停止/再開・キャンセル。"""
from __future__ import annotations

import glob
import itertools
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import errors
from .procs import WorkerProcess
from ..i18n import N_, tr

ACTIVE = ('running',)
FINAL = ('done', 'error', 'cancelled')
_ids = itertools.count(1)


@dataclass
class Job:
    spec: dict[str, Any]
    title: str = ''
    thumbnail: str = ''
    start_at: float | None = None
    id: int = field(default_factory=lambda: next(_ids))
    status: str = 'queued'           # queued | scheduled | running | paused | done | error | cancelled
    created_at: float = field(default_factory=time.time)
    downloaded: int = 0
    total: int = 0
    speed: float | None = None
    eta: int | None = None
    stage: str = ''
    item_label: str = ''             # プレイリスト時の「3/12」
    files: list[dict] = field(default_factory=list)
    error: str = ''
    error_hint: str = ''
    error_raw: str = ''
    uploader: str = ''
    extractor: str = ''
    log: list[str] = field(default_factory=list)
    partials: set[str] = field(default_factory=set)   # 途中ファイルの削除候補(ワーカーが報告したものだけ)
    waiting_live: bool = False

    @property
    def fraction(self) -> float:
        return min(1.0, self.downloaded / self.total) if self.total else 0.0

    def add_log(self, line: str) -> None:
        self.log.append(line)
        if len(self.log) > 2000:
            del self.log[:500]


class QueueManager(QObject):
    job_added = Signal(int)
    job_changed = Signal(int)
    job_removed = Signal(int)
    job_finished = Signal(int)       # done / error / cancelled に到達
    counts_changed = Signal()

    def __init__(self, env: Callable[[], dict], concurrency: int = 2, parent: QObject | None = None):
        super().__init__(parent)
        self.env = env                  # 実行直前の ffmpeg / JS ランタイム
        self.jobs: dict[int, Job] = {}
        self.order: list[int] = []
        self.procs: dict[int, WorkerProcess] = {}
        self.concurrency = max(1, concurrency)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._pump)
        self._tick.start()

    # --- 操作 ---
    def add(self, spec: dict[str, Any], *, title: str = '', thumbnail: str = '', start_at: float | None = None) -> Job:
        job = Job(spec=dict(spec), title=title or spec.get('url', ''), thumbnail=thumbnail, start_at=start_at)
        if start_at and start_at > time.time():
            job.status = 'scheduled'
        self.jobs[job.id] = job
        self.order.append(job.id)
        self.job_added.emit(job.id)
        self.counts_changed.emit()
        self._pump()
        return job

    def set_concurrency(self, n: int) -> None:
        self.concurrency = max(1, n)
        self._pump()

    def pause(self, job_id: int) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.status == 'running':
            job.status = 'paused'   # finished ハンドラで上書きしないよう先に設定
            self.procs[job_id].kill()
        elif job.status in ('queued', 'scheduled'):
            job.status = 'paused'
        self._changed(job)

    def resume(self, job_id: int) -> None:
        job = self.jobs.get(job_id)
        if job and job.status in ('paused', 'error', 'cancelled'):
            job.status = 'scheduled' if job.start_at and job.start_at > time.time() else 'queued'
            job.error = job.error_hint = job.error_raw = ''
            self._changed(job)
            self._pump()

    def cancel(self, job_id: int) -> None:
        job = self.jobs.get(job_id)
        if not job or job.status in FINAL:
            return
        was_running = job.status == 'running'
        job.status = 'cancelled'
        if was_running:
            self.procs[job_id].kill()   # 削除は _on_finished で(プロセスがファイルを掴んでいる間は消せない)
        else:
            _remove_partials(job)
            self._changed(job)
            self.job_finished.emit(job.id)

    def remove(self, job_id: int) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.status == 'running':
            self.cancel(job_id)
            return
        if job.status == 'error':
            _remove_partials(job)   # 一覧から消すと再試行できないので、途中ファイルも残さない
        self.jobs.pop(job_id)
        self.order.remove(job_id)
        self.job_removed.emit(job_id)
        self.counts_changed.emit()

    def clear_finished(self) -> None:
        for jid in [j for j in self.order if self.jobs[j].status in FINAL]:
            self.remove(jid)

    def pause_all(self) -> None:
        for jid in list(self.order):
            if self.jobs[jid].status in ('running', 'queued', 'scheduled'):
                self.pause(jid)

    def resume_all(self) -> None:
        for jid in list(self.order):
            if self.jobs[jid].status == 'paused':
                self.resume(jid)

    def running_count(self) -> int:
        return sum(1 for j in self.jobs.values() if j.status == 'running')

    def pending_count(self) -> int:
        return sum(1 for j in self.jobs.values() if j.status in ('running', 'queued', 'scheduled', 'paused'))

    def shutdown(self) -> None:
        self._tick.stop()
        for jid, proc in list(self.procs.items()):
            self.jobs[jid].status = 'paused'
            proc.kill()

    # --- 内部 ---
    def _changed(self, job: Job) -> None:
        self.job_changed.emit(job.id)
        self.counts_changed.emit()

    def _pump(self) -> None:
        now = time.time()
        for jid in self.order:
            job = self.jobs[jid]
            if job.status == 'scheduled' and job.start_at and job.start_at <= now:
                job.status = 'queued'
                job.add_log(tr('[予約] {time} 開始時刻になりました', time=time.strftime('%H:%M:%S')))
                self._changed(job)
        for jid in self.order:
            if self.running_count() >= self.concurrency:
                break
            if self.jobs[jid].status == 'queued':
                self._start(self.jobs[jid])

    def _start(self, job: Job) -> None:
        job.status = 'running'
        job.stage = tr('準備中')
        job.speed = job.eta = None
        job.waiting_live = False
        proc = WorkerProcess(self)
        self.procs[job.id] = proc
        proc.message.connect(lambda m, j=job: self._on_message(j, m))
        proc.finished.connect(lambda code, j=job: self._on_finished(j, code))
        proc.start('download', {**job.spec, **self.env()})
        self._changed(job)

    def _on_message(self, job: Job, m: dict) -> None:
        t = m.get('t')
        if t == 'progress':
            job.downloaded = int(m.get('downloaded') or 0)
            job.total = int(m.get('total') or 0)
            job.speed = m.get('speed')
            job.eta = m.get('eta')
            job.stage = tr('完了処理中') if m.get('done') else tr('ダウンロード中')
            if m.get('filename'):
                job.partials.add(str(m['filename']))
            job.waiting_live = False
        elif t == 'meta':
            if m.get('title'):
                job.title = m['title']
            job.uploader = m.get('uploader') or job.uploader
            job.extractor = m.get('extractor') or job.extractor
            if m.get('playlist_index') and m.get('n_entries'):
                job.item_label = f'{m["playlist_index"]}/{m["n_entries"]}'
            job.add_log(tr('[開始] {title}', title=m.get('title')))
        elif t == 'stage':
            job.stage = tr(_STAGE_NAMES.get(m.get('name') or '', m.get('name') or ''))
        elif t == 'file':
            job.files.append({'path': m.get('path'), 'size': m.get('size')})
            job.add_log(tr('[保存] {path}', path=m.get('path')))
        elif t == 'log':
            msg = str(m.get('msg') or '')
            job.add_log(msg)
            if m.get('level') == 'error' and not job.error_raw:
                job.error_raw = msg
            if msg.startswith('[wait]') or 'Waiting for' in msg or 'Remaining time until next attempt' in msg:
                job.waiting_live = True
                job.stage = tr('ライブ開始待ち')
        elif t == 'error':
            job.error_raw = str(m.get('msg') or job.error_raw)
            if m.get('trace'):
                job.add_log(m['trace'])
        self.job_changed.emit(job.id)

    def _on_finished(self, job: Job, code: int) -> None:
        proc = self.procs.pop(job.id, None)
        if proc is not None:
            proc.deleteLater()
        if job.status == 'running':
            if code == 0:
                job.status = 'done'
                job.stage = tr('完了')
            else:
                job.status = 'error'
                raw = job.error_raw or (proc.stderr_tail[-1] if proc and proc.stderr_tail else tr('終了コード {code}', code=code))
                job.error_raw = raw
                job.error, job.error_hint = errors.explain(raw)
                if proc and proc.stderr_tail:
                    job.add_log('\n'.join(proc.stderr_tail))
        elif job.status == 'paused':
            job.stage = tr('一時停止')
        elif job.status == 'cancelled':
            _remove_partials(job)
            job.stage = ''
        job.speed = job.eta = None
        self._changed(job)
        if job.status in FINAL:
            self.job_finished.emit(job.id)
        self._pump()


def _remove_partials(job: Job) -> None:
    """キャンセル時の後始末。ワーカーが報告したパスのうち、保存先配下で最終ファイルでないものだけ消す。"""
    out_dir = os.path.abspath(job.spec.get('out_dir') or '.')
    finals = {os.path.abspath(f['path']) for f in job.files if f.get('path')}
    removed = 0
    for base in job.partials:
        base = os.path.abspath(base)
        if os.path.commonpath([out_dir, base]) != out_dir:
            continue
        candidates = [base + '.part', base + '.ytdl'] + glob.glob(glob.escape(base) + '.part-Frag*')
        if base not in finals:
            candidates.append(base)
        for c in candidates:
            try:
                if os.path.isfile(c):
                    os.remove(c)
                    removed += 1
            except OSError as e:
                job.add_log(tr('[後始末] 削除できません: {path} ({error})', path=c, error=e))
    if removed:
        job.add_log(tr('[後始末] 途中ファイルを {count} 個削除しました', count=removed))
    job.partials.clear()


_STAGE_NAMES = {
    'Merger': N_('結合中'), 'ExtractAudio': N_('音声変換中'), 'VideoRemuxer': N_('コンテナ変換中'), 'Metadata': N_('メタデータ書き込み'),
    'EmbedSubtitle': N_('字幕埋め込み'), 'EmbedThumbnail': N_('サムネ埋め込み'), 'ThumbnailsConvertor': N_('サムネ変換'),
    'MoveFiles': N_('移動中'), 'FixupM3u8': N_('修正中'), 'FixupM4a': N_('修正中'), 'FixupStretched': N_('修正中'),
    'FixupDuplicateMoov': N_('修正中'), 'FixupTimestamp': N_('修正中'), 'SubtitlesConvertor': N_('字幕変換'),
}
