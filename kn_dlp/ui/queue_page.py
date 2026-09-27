"""キュー画面: ジョブカードの一覧と、選択中ジョブのログ。"""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QScrollArea, QSpinBox,
                               QSplitter, QVBoxLayout, QWidget)

from ..timeparse import format_seconds
from .queue import FINAL, Job, QueueManager
from . import theme
from .theme import icon
from .widgets import button, human_size, human_speed, label, reveal, restyle
from ..i18n import N_, tr

STATUS_TEXT = {'queued': N_('待機中'), 'scheduled': N_('予約'), 'running': N_('実行中'), 'paused': N_('一時停止'),
               'done': N_('完了'), 'error': N_('エラー'), 'cancelled': N_('キャンセル')}


class JobCard(QFrame):
    clicked = Signal(int)

    def __init__(self, job: Job, manager: QueueManager, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('jobCard')
        self.job_id = job.id
        self.manager = manager
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(7)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.status = QLabel()
        self.status.setObjectName('chip')
        self.title = label('', 'h2')
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        top.addWidget(self.status)
        top.addWidget(self.title, 1)
        self.pause_btn = button('', 'icon', tip=tr('一時停止'))
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.folder_btn = button('', 'icon', tip=tr('保存先を開く'))
        self.folder_btn.clicked.connect(self._reveal)
        self.close_btn = button('', 'icon', tip=tr('キャンセル'))
        self.close_btn.clicked.connect(self._close)
        for b in (self.pause_btn, self.folder_btn, self.close_btn):
            b.setIconSize(QSize(16, 16))
            top.addWidget(b)
        lay.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)
        self.detail = label('', 'muted')
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.detail)
        self.err = label('', 'errText', wrap=True)
        self.err.hide()
        lay.addWidget(self.err)
        self.update_from(job)

    def mousePressEvent(self, ev):
        self.clicked.emit(self.job_id)
        super().mousePressEvent(ev)

    def set_selected(self, on: bool) -> None:
        self.setProperty('selected', on)
        restyle(self)

    def update_from(self, job: Job) -> None:
        self.title.setText(job.title)
        self.title.setToolTip(job.spec.get('url', ''))
        color = theme.status_color(job.status)
        self.status.setText(tr(STATUS_TEXT.get(job.status, job.status)))
        self.status.setStyleSheet(f'color: {color};')
        if job.status == 'done':
            self.bar.setValue(1000)
        elif job.total:
            self.bar.setValue(int(job.fraction * 1000))
        elif job.status == 'running' and job.waiting_live:
            self.bar.setValue(0)
        self.bar.setRange(0, 0 if (job.status == 'running' and not job.total and not job.waiting_live) else 1000)
        self.bar.setProperty('state', {'done': 'done', 'error': 'error', 'paused': 'paused'}.get(job.status, ''))
        restyle(self.bar)
        self.detail.setText(self._detail(job))
        if job.status == 'error':
            self.err.setText(f'{job.error}\n{job.error_hint}')
            self.err.setToolTip(job.error_raw)
            self.err.show()
        else:
            self.err.hide()
        self.pause_btn.setVisible(job.status not in FINAL or job.status in ('error', 'cancelled'))
        if job.status in ('paused', 'error', 'cancelled'):
            self.pause_btn.setIcon(icon('play'))
            self.pause_btn.setToolTip(tr('再開') if job.status == 'paused' else tr('再試行'))
        else:
            self.pause_btn.setIcon(icon('pause'))
            self.pause_btn.setToolTip(tr('一時停止'))
        self.folder_btn.setIcon(icon('folder'))   # 配色の切り替えに追従するため毎回当て直す
        self.close_btn.setIcon(icon('close'))
        self.close_btn.setToolTip(tr('一覧から消す') if job.status in FINAL else tr('キャンセル'))
        self.folder_btn.setEnabled(bool(job.files) or job.status == 'done')

    @staticmethod
    def _detail(job: Job) -> str:
        bits = []
        if job.item_label:
            bits.append(job.item_label)
        if job.status == 'scheduled' and job.start_at:
            left = max(0, int(job.start_at - time.time()))
            bits.append(tr('{time} に開始 (あと {left})', time=time.strftime('%m/%d %H:%M', time.localtime(job.start_at)), left=format_seconds(left)))
        if job.status == 'running':
            if job.stage:
                bits.append(job.stage)
            if job.total:
                bits.append(f'{human_size(job.downloaded)} / {human_size(job.total)}  ({job.fraction * 100:.1f}%)')
            elif job.downloaded:
                bits.append(human_size(job.downloaded))
            if job.speed:
                bits.append(human_speed(job.speed))
            if job.eta:
                bits.append(tr('残り {eta}', eta=format_seconds(job.eta)))
        if job.status == 'done':
            size = sum(f.get('size') or 0 for f in job.files)
            if job.files:
                bits.append(tr('{count} ファイル · {size}', count=len(job.files), size=human_size(size)))
            if job.skipped or not job.files:   # ダウンロード済みの記録で飛ばしたことを見せる
                bits.append(job.stage or tr('完了'))
        if job.status == 'paused':
            if job.stage and job.stage != tr('一時停止'):   # 「前回の終了時から一時停止中」など
                bits.append(job.stage)
            bits.append(tr('再開すると途中から続けます'))
        return '  ·  '.join(bits) or job.spec.get('url', '')

    def _toggle_pause(self) -> None:
        job = self.manager.jobs.get(self.job_id)
        if not job:
            return
        if job.status in ('paused', 'error', 'cancelled'):
            self.manager.resume(self.job_id)
        else:
            self.manager.pause(self.job_id)

    def _close(self) -> None:
        job = self.manager.jobs.get(self.job_id)
        if not job:
            return
        if job.status in FINAL or job.status == 'paused':
            if job.status == 'paused':
                self.manager.cancel(self.job_id)
            self.manager.remove(self.job_id)
        else:
            self.manager.cancel(self.job_id)

    def _reveal(self) -> None:
        job = self.manager.jobs.get(self.job_id)
        if job and job.files:
            reveal(job.files[-1]['path'])
        elif job:
            reveal(job.spec.get('out_dir'))


class QueuePage(QWidget):
    def __init__(self, manager: QueueManager, settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('page')
        self.manager = manager
        self.settings = settings
        self.cards: dict[int, JobCard] = {}
        self.selected: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 26, 32, 20)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label(tr('キュー'), 'h1'))
        head.addStretch(1)
        head.addWidget(label(tr('同時実行'), 'muted'))
        self.conc = QSpinBox()
        self.conc.setRange(1, 8)
        self.conc.setValue(manager.concurrency)
        self.conc.valueChanged.connect(self._set_conc)
        head.addWidget(self.conc)
        pa = button(tr('すべて一時停止'), 'ghost')
        pa.clicked.connect(manager.pause_all)
        ra = button(tr('すべて再開'), 'ghost')
        ra.clicked.connect(manager.resume_all)
        cl = button(tr('完了を消去'), 'ghost')
        cl.clicked.connect(manager.clear_finished)
        for b in (pa, ra, cl):
            head.addWidget(b)
        lay.addLayout(head)

        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName('page')
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.setSpacing(10)
        self.empty = label(tr('キューは空です。「新規ダウンロード」から URL を追加してください。'), 'muted')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(160)
        self.list.addWidget(self.empty)
        self.list.addStretch(1)
        scroll.setWidget(holder)
        split.addWidget(scroll)
        logbox = QWidget()
        ll = QVBoxLayout(logbox)
        ll.setContentsMargins(0, 8, 0, 0)
        ll.setSpacing(6)
        lh = QHBoxLayout()
        self.log_title = label(tr('ログ'), 'muted')
        lh.addWidget(self.log_title, 1)
        copy = button(tr('コピー'), 'ghost')
        copy.clicked.connect(lambda: (self.log.selectAll(), self.log.copy(), self.log.moveCursor(self.log.textCursor().MoveOperation.End)))
        lh.addWidget(copy)
        ll.addLayout(lh)
        self.log = QPlainTextEdit()
        self.log.setObjectName('log')
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        ll.addWidget(self.log)
        split.addWidget(logbox)
        split.setSizes([520, 180])
        lay.addWidget(split, 1)

        manager.job_added.connect(self._on_added)
        manager.job_changed.connect(self._on_changed)
        manager.job_removed.connect(self._on_removed)
        theme.notifier().changed.connect(lambda _mode: self._repaint_all())

    def _repaint_all(self) -> None:
        for jid, card in self.cards.items():
            if job := self.manager.jobs.get(jid):
                card.update_from(job)

    def _set_conc(self, n: int) -> None:
        self.manager.set_concurrency(n)
        self.settings['concurrency'] = n
        self.settings.save()

    def _on_added(self, jid: int) -> None:
        card = JobCard(self.manager.jobs[jid], self.manager)
        card.clicked.connect(self._select)
        self.cards[jid] = card
        self.list.insertWidget(self.list.count() - 1, card)
        self.empty.hide()
        if self.selected is None:
            self._select(jid)

    def _on_changed(self, jid: int) -> None:
        job = self.manager.jobs.get(jid)
        card = self.cards.get(jid)
        if job and card:
            card.update_from(job)
            if jid == self.selected:
                self._render_log(job)

    def _on_removed(self, jid: int) -> None:
        card = self.cards.pop(jid, None)
        if card:
            card.deleteLater()
        if self.selected == jid:
            self.selected = None
            self.log.clear()
            self.log_title.setText(tr('ログ'))
        self.empty.setVisible(not self.cards)

    def _select(self, jid: int) -> None:
        if self.selected in self.cards:
            self.cards[self.selected].set_selected(False)
        self.selected = jid
        self.cards[jid].set_selected(True)
        self.log.clear()
        self._log_len = 0
        self._render_log(self.manager.jobs[jid])

    def _render_log(self, job: Job) -> None:
        self.log_title.setText(tr('ログ — {title}', title=job.title))
        n = getattr(self, '_log_len', 0)
        if n > len(job.log):  # ログが間引かれた
            self.log.clear()
            n = 0
        for line in job.log[n:]:
            self.log.appendPlainText(line)
        self._log_len = len(job.log)

    def tick(self) -> None:
        """予約の残り時間表示を更新(1 秒ごと)。"""
        for jid, card in self.cards.items():
            job = self.manager.jobs.get(jid)
            if job and job.status == 'scheduled':
                card.update_from(job)
