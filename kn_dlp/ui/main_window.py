"""メインウィンドウ: サイドバー + ページ。完了通知と履歴記録もここで行う。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QMainWindow, QMessageBox, QStackedWidget, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from .. import APP_DISPLAY_NAME, __version__
from ..history import History
from ..settings import Settings
from .history_page import HistoryPage
from .new_page import NewPage
from .queue import QueueManager
from .queue_page import QueuePage
from .settings_page import SettingsPage
from . import theme
from .theme import app_icon
from .widgets import button, label
from ..i18n import tr


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1180, 820)
        self.setMinimumSize(940, 640)
        self.setAcceptDrops(True)
        self.settings = settings
        self.history = History()

        root = QWidget()
        root.setObjectName('root')
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget()
        side.setObjectName('sidebar')
        side.setFixedWidth(210)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 22, 14, 16)
        sv.setSpacing(4)
        self.brand = label('', 'brand')
        self.brand.setTextFormat(Qt.TextFormat.RichText)
        self._paint_brand()
        theme.notifier().changed.connect(lambda _mode: self._paint_brand())
        sv.addWidget(self.brand)
        sv.addWidget(label('yt-dlp desktop', 'brandSub'))
        sv.addSpacing(22)

        self.pages = QStackedWidget()
        self.settings_page = SettingsPage(self.settings)
        self.queue = QueueManager(self.settings_page.env, self.settings['concurrency'], self)
        self.new_page = NewPage(self.settings, self.settings_page.env)
        self.queue_page = QueuePage(self.queue, self.settings)
        self.history_page = HistoryPage(self.history)
        self.nav = QButtonGroup(self)
        self.nav_buttons = {}
        for i, (key, text, page) in enumerate((('new', '＋  ' + tr('新規ダウンロード'), self.new_page),
                                               ('queue', '⇣  ' + tr('キュー'), self.queue_page),
                                               ('history', '◷  ' + tr('履歴'), self.history_page),
                                               ('settings', '⚙  ' + tr('設定'), self.settings_page))):
            b = button(text, 'nav')
            b.setCheckable(True)
            self.nav.addButton(b, i)
            self.nav_buttons[key] = b
            sv.addWidget(b)
            self.pages.addWidget(page)
        self.nav.idClicked.connect(self._go)
        sv.addStretch(1)
        self.ver_side = label('', 'faint')
        self.ver_side.setWordWrap(True)
        sv.addWidget(self.ver_side)
        self.upd_side = button(tr('yt-dlp の更新があります'), 'updLink')
        self.upd_side.clicked.connect(lambda: self._go(3))
        self.upd_side.hide()
        sv.addWidget(self.upd_side)
        sv.addWidget(label(f'v{__version__}', 'faint'))
        h.addWidget(side)
        h.addWidget(self.pages, 1)

        # 配線
        self.new_page.enqueue.connect(self._enqueue)
        self.new_page.status_message.connect(lambda t: self.statusBar().showMessage(t, 5000))
        self.history_page.redownload.connect(self._redownload)
        self.queue.job_finished.connect(self._on_finished)
        self.queue.counts_changed.connect(self._update_badge)
        self.settings_page.ytdlp_changed.connect(self._on_ytdlp)
        # 同時実行数は設定画面とキュー画面の両方にある。同じ値の setValue は発火しないので往復しない
        self.settings_page.conc.valueChanged.connect(self.queue_page.conc.setValue)
        self.queue_page.conc.valueChanged.connect(self.settings_page.conc.setValue)
        self.settings_page.refresh_version()

        self.tray = QSystemTrayIcon(app_icon(), self) if QSystemTrayIcon.isSystemTrayAvailable() else None
        if self.tray:
            self.tray.setToolTip(APP_DISPLAY_NAME)
            self.tray.messageClicked.connect(self._raise)
            self.tray.show()

        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self.queue_page.tick)
        self._tick.start()
        QShortcut(QKeySequence('Ctrl+L'), self, activated=lambda: (self._go(0), self.new_page.url.setFocus()))
        self._go(0)
        if self.settings['check_update_on_start']:
            QTimer.singleShot(1500, lambda: self.settings_page.check_update(silent=True))

    def _paint_brand(self) -> None:
        self.brand.setText(f'KN <span style="color:{theme.T["accent"]}">DLP</span>')

    def _go(self, idx: int) -> None:
        self.nav.button(idx).setChecked(True)
        self.pages.setCurrentIndex(idx)
        if idx == 2:
            self.history_page.refresh()

    def _raise(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _enqueue(self, spec: dict, title: str, thumb: str, start_at) -> None:
        self.queue.add(spec, title=title, thumbnail=thumb, start_at=start_at)
        self.settings.save()
        self.statusBar().showMessage(tr('キューに追加: {title}', title=title), 4000)
        self._go(1)

    def _redownload(self, job: dict) -> None:
        self.new_page.apply_spec(job)
        self._go(0)
        self.statusBar().showMessage(tr('履歴の設定を読み込みました。内容を確認して追加してください'), 6000)

    def _update_badge(self) -> None:
        n = self.queue.pending_count()
        self.nav_buttons['queue'].setText('⇣  ' + tr('キュー') + (f'  ({n})' if n else ''))

    def _on_ytdlp(self, ver: str, has_update: bool) -> None:
        self.ver_side.setText(f'yt-dlp {ver}')
        self.upd_side.setVisible(has_update)

    def _on_finished(self, jid: int) -> None:
        job = self.queue.jobs.get(jid)
        if not job:
            return
        first = job.files[-1] if job.files else {}
        self.history.add(job.spec, status=job.status, title=job.title, uploader=job.uploader, extractor=job.extractor,
                         filepath=first.get('path') or '', filesize=sum(f.get('size') or 0 for f in job.files) or None,
                         error=f'{job.error} / {job.error_raw}' if job.status == 'error' else '',
                         created_at=job.created_at)
        if self.pages.currentIndex() == 2:
            self.history_page.refresh()
        if self.tray and job.status in ('done', 'error') and not self.isActiveWindow():
            icon = QSystemTrayIcon.MessageIcon.Information if job.status == 'done' else QSystemTrayIcon.MessageIcon.Warning
            self.tray.showMessage(tr('ダウンロード完了') if job.status == 'done' else tr('ダウンロード失敗'), job.title, icon, 5000)

    # ドラッグ&ドロップで URL(と、プラグインの .py / .zip)を受け取る
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() and md.urls()[0].isLocalFile():
            path = md.urls()[0].toLocalFile()
            if path.lower().endswith(('.py', '.zip')):   # プラグインの追加
                self._go(3)
                # ドロップ処理中にモーダルを出すとエクスプローラ側のドラッグが固まるので、処理を抜けてから聞く
                QTimer.singleShot(0, lambda: self.settings_page.install_plugin_file(path))
            return
        url = md.urls()[0].toString() if md.hasUrls() else md.text()
        if url.startswith(('http://', 'https://')):
            self._go(0)
            self.new_page.set_url(url)

    def closeEvent(self, e: QCloseEvent) -> None:
        if self.queue.running_count() and QMessageBox.question(
                self, APP_DISPLAY_NAME, tr('実行中のダウンロードがあります。中断して終了しますか?\n(途中のファイルは残り、次回は最初から追加し直す必要があります)')) \
                != QMessageBox.StandardButton.Yes:
            e.ignore()
            return
        self.queue.shutdown()
        self.settings.save()
        self.history.close()
        if self.tray:
            self.tray.hide()
        e.accept()
