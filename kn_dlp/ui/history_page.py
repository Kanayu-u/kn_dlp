"""履歴画面(E): 検索・フォルダを開く・再ダウンロード・削除。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLineEdit, QMenu, QMessageBox, QTableView,
                               QVBoxLayout, QWidget)

from ..history import History
from . import theme
from .widgets import button, human_size, label, open_path, reveal
from ..i18n import N_, tr

STATUS_TEXT = {'done': N_('完了'), 'error': N_('エラー'), 'cancelled': N_('キャンセル')}
COLS = [N_('日時'), N_('タイトル'), N_('投稿者'), N_('状態'), N_('サイズ'), N_('ファイル')]


class HistoryPage(QWidget):
    redownload = Signal(dict)

    def __init__(self, history: History, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('page')
        self.history = history
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 26, 32, 20)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label(tr('履歴'), 'h1'))
        head.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('タイトル・URL・投稿者で検索'))
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(200)
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        head.addWidget(self.search)
        lay.addLayout(head)

        self.model = QStandardItemModel(0, len(COLS))
        self.model.setHorizontalHeaderLabels([tr(c) for c in COLS])
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(True)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 380)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 80)
        self.table.doubleClicked.connect(lambda _: self._open_file())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)

        foot = QHBoxLayout()
        self.count = label('', 'muted')
        foot.addWidget(self.count, 1)
        for text, fn, name in ((tr('再生'), self._open_file, ''), (tr('フォルダを開く'), self._reveal, ''),
                               (tr('再ダウンロード'), self._redownload, ''), (tr('削除'), self._delete, 'danger'),
                               (tr('すべて消去'), self._clear, 'danger')):
            b = button(text, name)
            b.clicked.connect(fn)
            foot.addWidget(b)
        lay.addLayout(foot)
        theme.notifier().changed.connect(lambda _mode: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        rows = self.history.search(self.search.text())
        self.model.removeRows(0, self.model.rowCount())
        for r in rows:
            exists = bool(r['filepath']) and Path(r['filepath']).exists()
            items = [
                QStandardItem(time.strftime('%Y/%m/%d %H:%M', time.localtime(r['created_at']))),
                QStandardItem(r['title'] or r['url']),
                QStandardItem(r['uploader'] or ''),
                QStandardItem(tr(STATUS_TEXT.get(r['status'], r['status']))),
                QStandardItem(human_size(r['filesize'])),
                QStandardItem((r['filepath'] or '') if exists or not r['filepath'] else tr('(見つかりません) {filepath}', filepath=r['filepath'])),
            ]
            items[0].setData(r['id'], Qt.ItemDataRole.UserRole)
            items[1].setToolTip(r['url'])
            items[3].setForeground(_brush(theme.status_color(r['status'])))
            if r['error']:
                items[3].setToolTip(r['error'])
            if r['filepath'] and not exists:
                items[5].setForeground(_brush(theme.status_color('cancelled')))
            self.model.appendRow(items)
        self.count.setText(tr('{count} 件', count=len(rows)) + (tr(' (上限 500 件まで表示)') if len(rows) >= 500 else ''))

    def _selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self.model.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]

    def _first(self) -> dict | None:
        ids = self._selected_ids()
        return self.history.get(ids[0]) if ids else None

    def _open_file(self) -> None:
        r = self._first()
        if r:
            open_path(r['filepath'])

    def _reveal(self) -> None:
        r = self._first()
        if r and r['filepath']:
            reveal(r['filepath'])

    def _redownload(self) -> None:
        ids = self._selected_ids()
        if ids and (job := self.history.job_of(ids[0])):
            self.redownload.emit(job)

    def _delete(self) -> None:
        ids = self._selected_ids()
        if ids:
            self.history.delete(ids)
            self.refresh()

    def _clear(self) -> None:
        if QMessageBox.question(self, tr('履歴'), tr('履歴をすべて消去しますか? (ダウンロード済みのファイルは消えません)')) \
                == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh()

    def _menu(self, pos) -> None:
        if not self._selected_ids():
            return
        m = QMenu(self)
        m.addAction(tr('再生'), self._open_file)
        m.addAction(tr('フォルダを開く'), self._reveal)
        m.addAction(tr('再ダウンロード'), self._redownload)
        m.addAction(tr('URL をコピー'), self._copy_url)
        m.addSeparator()
        m.addAction(tr('履歴から削除'), self._delete)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_url(self) -> None:
        from PySide6.QtGui import QGuiApplication
        r = self._first()
        if r:
            QGuiApplication.clipboard().setText(r['url'])


def _brush(color: str):
    from PySide6.QtGui import QBrush, QColor
    return QBrush(QColor(color))
