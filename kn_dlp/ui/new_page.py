"""新規ダウンロード画面: URL 解析 → オプション → キュー投入。"""
from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import QDateTime, Qt, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import errors
from ..options import AUDIO_CODECS, COOKIE_BROWSERS, JOB_DEFAULTS, JobError, normalize_job, validate_job
from ..settings import Settings
from ..timeparse import format_seconds
from .procs import WorkerProcess
from .widgets import Card, Segmented, button, human_size, label, restyle
from ..i18n import N_, tr

QUALITY_LABELS = [('best', N_('最高画質')), ('2160', '2160p (4K)'), ('1440', '1440p'), ('1080', '1080p'),
                  ('720', '720p'), ('480', '480p'), ('360', '360p')]
CONTAINER_LABELS = [('auto', N_('自動 (無変換)')), ('mp4', N_('MP4 (互換性重視)')), ('mkv', 'MKV'), ('webm', 'WebM')]
AUDIO_LABELS = {'best': N_('元の形式のまま'), 'mp3': 'MP3', 'm4a': 'M4A (AAC)', 'opus': 'Opus', 'flac': N_('FLAC (可逆)'),
                'wav': N_('WAV (無圧縮)')}
AUDIO_QUALITY = [('0', N_('最高 (VBR 0)')), ('2', N_('高 (VBR 2)')), ('5', N_('標準 (VBR 5)')), ('320K', '320 kbps'),
                 ('192K', '192 kbps'), ('128K', '128 kbps')]
BROWSER_LABELS = {'': N_('使わない'), 'firefox': N_('Firefox (推奨)'), 'chrome': 'Chrome', 'edge': 'Edge', 'brave': 'Brave',
                  'opera': 'Opera', 'vivaldi': 'Vivaldi', 'chromium': 'Chromium', 'whale': 'Whale'}


def _combo(items: list[tuple[str, str]]) -> QComboBox:
    cb = QComboBox()
    for key, text in items:
        cb.addItem(tr(text), key)
    return cb


def _set_combo(cb: QComboBox, key: Any) -> None:
    i = cb.findData(key)
    if i >= 0:
        cb.setCurrentIndex(i)


def _row(*widgets, stretch_last: bool = False) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(8)
    for w in widgets:
        if isinstance(w, str):
            lb = QLabel(w)
            lb.setObjectName('muted')
            lb.setMinimumWidth(78)
            lay.addWidget(lb)
        else:
            lay.addWidget(w)
    if not stretch_last:
        lay.addStretch(1)
    return lay


class FormatDialog(QDialog):
    """形式一覧から映像1つ+音声1つ(または単体1つ)を選ぶ。"""

    COLS = ['ID', N_('拡張子'), N_('解像度'), 'fps', N_('映像'), N_('音声'), N_('ビットレート'), N_('サイズ'), N_('備考')]

    def __init__(self, formats: list[dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr('形式を個別に選ぶ'))
        self.resize(900, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(label(tr('映像のみ 1 つと音声のみ 1 つを Ctrl+クリックで選ぶと結合します。映像+音声入りは 1 つだけ選びます。'),
                            'muted', wrap=True))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.formats = [f for f in formats if f.get('format_id')]
        for f in reversed(self.formats):
            r = self.table.rowCount()
            self.table.insertRow(r)
            v = f.get('vcodec') or ''
            a = f.get('acodec') or ''
            vals = [f.get('format_id'), f.get('ext'), f.get('resolution') or '', f.get('fps') or '',
                    '—' if v == 'none' else v, '—' if a == 'none' else a,
                    f'{f["tbr"]:.0f}k' if f.get('tbr') else '',
                    human_size(f.get('filesize') or f.get('filesize_approx')), f.get('format_note') or '']
            for c, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                item.setData(Qt.ItemDataRole.UserRole, f)
                self.table.setItem(r, c, item)
        lay.addWidget(self.table, 1)
        self.hint = label('', 'warnText')
        lay.addWidget(self.hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.result_format = ''

    def _accept(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        fmts = [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]
        if len(fmts) == 1:
            self.result_format = fmts[0]['format_id']
        elif len(fmts) == 2:
            video = [f for f in fmts if f.get('vcodec') not in (None, 'none')]
            audio = [f for f in fmts if f.get('vcodec') in (None, 'none')]
            if len(video) != 1 or len(audio) != 1:
                self.hint.setText(tr('映像 1 つと音声 1 つの組み合わせにしてください'))
                return
            self.result_format = f'{video[0]["format_id"]}+{audio[0]["format_id"]}'
        else:
            self.hint.setText(tr('1 つか 2 つ選んでください'))
            return
        self.accept()


class NewPage(QWidget):
    enqueue = Signal(dict, str, str, object)      # spec, title, thumbnail, start_at
    status_message = Signal(str)

    def __init__(self, settings: Settings, env: Callable[[], dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('page')
        self.settings = settings
        self.env = env
        self.info: dict | None = None
        self.probe: WorkerProcess | None = None
        self.custom_format = ''
        self.net = QNetworkAccessManager(self)
        self.net.finished.connect(self._on_thumb)
        self._build()
        self._apply_profile(self.settings['last_profile'])
        self._reset_output_defaults()
        self._sync_enabled()

    # ---------- 構築 ----------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName('page')
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 26, 32, 20)
        lay.setSpacing(14)

        lay.addWidget(label(tr('新規ダウンロード'), 'h1'))
        lay.addWidget(label(tr('URL を貼り付けて解析するか、そのままキューに追加します。ウィンドウに URL をドロップしても入力できます。'),
                            'muted', wrap=True))

        self.url_bar = QFrame()
        self.url_bar.setObjectName('urlBar')
        ub = QHBoxLayout(self.url_bar)
        ub.setContentsMargins(14, 6, 8, 6)
        self.url = QLineEdit()
        self.url.setObjectName('url')
        self.url.setPlaceholderText('https://www.youtube.com/watch?v=…')
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.analyze)
        self.url.textChanged.connect(self._on_url_changed)
        self.url.installEventFilter(self)
        paste = button(tr('貼り付け'), 'ghost')
        paste.clicked.connect(self._paste)
        self.analyze_btn = button(tr('解析'), 'primary')
        self.analyze_btn.clicked.connect(self.analyze)
        ub.addWidget(self.url, 1)
        ub.addWidget(paste)
        ub.addWidget(self.analyze_btn)
        lay.addWidget(self.url_bar)
        self.probe_status = label('', 'muted', wrap=True)
        self.probe_status.hide()
        lay.addWidget(self.probe_status)

        # 解析結果
        self.info_card = Card()
        ic = QHBoxLayout()
        ic.setSpacing(18)
        self.thumb = QLabel()
        self.thumb.setFixedSize(256, 144)
        self.thumb.setObjectName('thumb')
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.addWidget(self.thumb)
        meta = QVBoxLayout()
        meta.setSpacing(6)
        self.title_lb = label('', 'title', wrap=True)
        self.meta_lb = label('', 'muted', wrap=True)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        meta.addWidget(self.title_lb)
        meta.addWidget(self.meta_lb)
        meta.addLayout(self.chips)
        meta.addStretch(1)
        fr = QHBoxLayout()
        self.formats_btn = button(tr('形式を個別に選ぶ…'))
        self.formats_btn.clicked.connect(self._pick_formats)
        self.custom_lb = label('', 'chip')
        self.custom_lb.hide()
        self.custom_clear = button(tr('解除'), 'ghost')
        self.custom_clear.hide()
        self.custom_clear.clicked.connect(lambda: self._set_custom(''))
        fr.addWidget(self.formats_btn)
        fr.addWidget(self.custom_lb)
        fr.addWidget(self.custom_clear)
        fr.addStretch(1)
        meta.addLayout(fr)
        ic.addLayout(meta, 1)
        self.info_card.body.addLayout(ic)
        self.info_card.hide()
        lay.addWidget(self.info_card)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._card_format(), 0, 0)
        grid.addWidget(self._card_subs(), 0, 1)
        grid.addWidget(self._card_range(), 1, 0)
        grid.addWidget(self._card_cookies(), 1, 1)
        grid.addWidget(self._card_live(), 2, 0)
        grid.addWidget(self._card_output(), 2, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

        # フッター
        footer = QFrame()
        footer.setObjectName('card')
        footer.setStyleSheet('QFrame#card { border-radius: 0; border-left: none; border-right: none; border-bottom: none; }')
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(32, 12, 32, 12)
        self.summary = label('', 'muted')
        fl.addWidget(self.summary, 1)
        self.add_btn = button(tr('キューに追加'), 'primary')
        self.add_btn.setMinimumWidth(160)
        self.add_btn.clicked.connect(self.submit)
        fl.addWidget(self.add_btn)
        outer.addWidget(footer)

    def _card_format(self) -> Card:
        card = Card(tr('形式'), tr('プロファイルで設定を保存・呼び出し'))
        self.profile = QComboBox()
        self.profile.setMinimumWidth(220)
        self._reload_profiles()
        self.profile.activated.connect(lambda _: self._apply_profile(self.profile.currentData()))
        save = button(tr('保存'), 'ghost', tip=tr('現在の設定をプロファイルとして保存'))
        save.clicked.connect(self._save_profile)
        self.del_profile = button(tr('削除'), 'ghost')
        self.del_profile.clicked.connect(self._delete_profile)
        card.body.addLayout(_row(tr('プロファイル'), self.profile, save, self.del_profile))
        self.mode = Segmented([('video', tr('動画')), ('audio', tr('音声のみ'))])
        self.mode.changed.connect(lambda _: self._sync_enabled())
        card.body.addLayout(_row(tr('種類'), self.mode))
        self.quality = _combo(QUALITY_LABELS)
        self.container = _combo(CONTAINER_LABELS)
        card.body.addLayout(_row(tr('画質'), self.quality, self.container))
        self.audio_codec = _combo([(k, AUDIO_LABELS[k]) for k in AUDIO_CODECS])
        self.audio_quality = _combo(AUDIO_QUALITY)
        card.body.addLayout(_row(tr('音声形式'), self.audio_codec, self.audio_quality))
        for w in (self.quality, self.container, self.audio_codec, self.audio_quality):
            w.currentIndexChanged.connect(lambda _: self._sync_enabled())
        return card

    def _card_range(self) -> Card:
        card = Card(tr('範囲を切り出す'), tr('指定した区間だけ取得'))
        self.range_on = QCheckBox(tr('区間を指定する'))
        self.range_on.toggled.connect(lambda _: self._sync_enabled())
        card.body.addWidget(self.range_on)
        self.range_start = QLineEdit()
        self.range_start.setPlaceholderText(tr('開始 (例 1:23)'))
        self.range_end = QLineEdit()
        self.range_end.setPlaceholderText(tr('終了 (空欄=最後まで)'))
        for w in (self.range_start, self.range_end):
            w.setMaximumWidth(150)
            w.textChanged.connect(lambda _: self._sync_enabled())
        card.body.addLayout(_row(tr('区間'), self.range_start, label(tr('〜'), 'muted'), self.range_end))
        self.precise = QCheckBox(tr('正確に切る (再エンコードするため遅い)'))
        card.body.addWidget(self.precise)
        return card

    def _card_subs(self) -> Card:
        card = Card(tr('字幕・チャプター・サムネ'))
        self.subs = QCheckBox(tr('字幕を取得'))
        self.auto_subs = QCheckBox(tr('自動生成字幕も含める'))
        self.subs.toggled.connect(lambda _: self._sync_enabled())
        card.body.addLayout(_row(self.subs, self.auto_subs))
        self.sub_langs = QLineEdit()
        self.sub_langs.setPlaceholderText(tr('ja,en  (all ですべて / ja.* のような正規表現も可)'))
        card.body.addLayout(_row(tr('言語'), self.sub_langs, stretch_last=True))
        self.subs_hint = label('', 'faint', wrap=True)
        self.subs_hint.hide()
        card.body.addWidget(self.subs_hint)
        self.embed_subs = QCheckBox(tr('字幕を動画に埋め込む'))
        self.chapters = QCheckBox(tr('チャプターを埋め込む'))
        card.body.addLayout(_row(self.embed_subs, self.chapters))
        self.embed_thumb = QCheckBox(tr('サムネイルを埋め込む'))
        self.metadata = QCheckBox(tr('タイトル等のメタデータを書き込む'))
        card.body.addLayout(_row(self.embed_thumb, self.metadata))
        return card

    def _card_live(self) -> Card:
        card = Card(tr('ライブ・予約'))
        self.wait_live = QCheckBox(tr('ライブ/プレミア開始を待って録画'))
        self.wait_interval = QSpinBox()
        self.wait_interval.setRange(15, 3600)
        self.wait_interval.setSuffix(tr(' 秒ごとに確認'))
        self.wait_live.toggled.connect(lambda _: self._sync_enabled())
        card.body.addLayout(_row(self.wait_live, self.wait_interval))
        self.live_from_start = QCheckBox(tr('配信中のライブを最初から取得 (対応サイトのみ・実験的)'))
        card.body.addWidget(self.live_from_start)
        self.schedule_on = QCheckBox(tr('開始時刻を予約'))
        self.schedule_at = QDateTimeEdit()
        self.schedule_at.setDisplayFormat('yyyy/MM/dd HH:mm')
        self.schedule_at.setCalendarPopup(True)
        self.schedule_on.toggled.connect(lambda _: self._sync_enabled())
        card.body.addLayout(_row(self.schedule_on, self.schedule_at))
        return card

    def _card_cookies(self) -> Card:
        card = Card(tr('ログインが必要な動画'), tr('ブラウザの Cookie を使う'))
        self.cookie_browser = QComboBox()
        for key in [''] + COOKIE_BROWSERS:
            self.cookie_browser.addItem(tr(BROWSER_LABELS.get(key, key)), key)
        self.cookie_browser.currentIndexChanged.connect(lambda _: self._sync_enabled())
        self.cookie_profile = QLineEdit()
        self.cookie_profile.setPlaceholderText(tr('プロファイル名 (省略可)'))
        card.body.addLayout(_row(tr('ブラウザ'), self.cookie_browser, self.cookie_profile))
        self.cookie_file = QLineEdit()
        self.cookie_file.setPlaceholderText(tr('または cookies.txt (Netscape 形式)'))
        pick = button(tr('参照'), 'ghost')
        pick.clicked.connect(self._pick_cookie_file)
        card.body.addLayout(_row(tr('ファイル'), self.cookie_file, pick, stretch_last=True))
        self.cookie_warn = label(tr('Chrome・Edge などは新しい暗号化方式のため読めないことがあり、起動中はファイルがロックされます。'
                                 'Firefox か cookies.txt を推奨します。Cookie はアプリに保存しません。'), 'warnText', wrap=True)
        card.body.addWidget(self.cookie_warn)
        return card

    def _card_output(self) -> Card:
        card = Card(tr('保存'))
        self.out_dir = QLineEdit()
        pick = button(tr('参照'), 'ghost')
        pick.clicked.connect(self._pick_dir)
        card.body.addLayout(_row(tr('保存先'), self.out_dir, pick, stretch_last=True))
        self.template = QLineEdit()
        self.template.setToolTip(tr('yt-dlp の出力テンプレート。例: %(uploader)s/%(title)s.%(ext)s'))
        card.body.addLayout(_row(tr('ファイル名'), self.template, stretch_last=True))
        self.playlist = QCheckBox(tr('URL がプレイリスト内の動画なら、プレイリスト全体を取得'))
        card.body.addWidget(self.playlist)
        self.rate = QLineEdit()
        self.rate.setPlaceholderText(tr('例 5M (空欄=無制限)'))
        self.rate.setMaximumWidth(160)
        card.body.addLayout(_row(tr('速度制限'), self.rate))
        return card

    # ---------- 状態 ----------
    def eventFilter(self, obj, ev):  # URL 欄のフォーカス枠
        if obj is self.url and ev.type() in (ev.Type.FocusIn, ev.Type.FocusOut):
            self.url_bar.setProperty('focus', ev.type() == ev.Type.FocusIn)
            restyle(self.url_bar)
        return super().eventFilter(obj, ev)

    def _reset_output_defaults(self) -> None:
        self.out_dir.setText(self.settings['download_dir'])
        if not self.template.text():
            self.template.setText(self.settings['template'])
        self.schedule_at.setDateTime(QDateTime.currentDateTime().addSecs(3600))

    def _sync_enabled(self) -> None:
        video = self.mode.value() == 'video'
        custom = bool(self.custom_format)
        self.quality.setEnabled(video and not custom)
        self.container.setEnabled(video)
        self.audio_codec.setEnabled(not video)
        self.audio_quality.setEnabled(not video and self.audio_codec.currentData() not in ('flac', 'wav', 'best'))
        on = self.range_on.isChecked()
        for w in (self.range_start, self.range_end, self.precise):
            w.setEnabled(on)
        subs = self.subs.isChecked()
        self.auto_subs.setEnabled(subs)
        self.sub_langs.setEnabled(subs)
        self.embed_subs.setEnabled(subs and video)
        self.wait_interval.setEnabled(self.wait_live.isChecked())
        self.schedule_at.setEnabled(self.schedule_on.isChecked())
        self.cookie_profile.setEnabled(bool(self.cookie_browser.currentData()))
        self.cookie_warn.setVisible(self.cookie_browser.currentData() not in ('', 'firefox'))
        self.del_profile.setEnabled(not self.settings.is_builtin(self.profile.currentData() or ''))
        self._update_summary()

    def _update_summary(self) -> None:
        parts = []
        if self.mode.value() == 'video':
            parts.append(tr('動画 · {quality}', quality=self.custom_format or self.quality.currentText()))
            if self.container.currentData() != 'auto':
                parts.append(self.container.currentData().upper())
        else:
            parts.append(tr('音声 · {codec}', codec=self.audio_codec.currentText()))
        if self.range_on.isChecked() and (self.range_start.text() or self.range_end.text()):
            parts.append(tr('{start}〜{end}', start=self.range_start.text() or '0', end=self.range_end.text() or tr('最後')))
        if self.subs.isChecked():
            parts.append(tr('字幕'))
        if self.cookie_browser.currentData() or self.cookie_file.text():
            parts.append('Cookie')
        if self.schedule_on.isChecked():
            parts.append(tr('予約') + ' ' + self.schedule_at.dateTime().toString('MM/dd HH:mm'))
        elif self.wait_live.isChecked():
            parts.append(tr('ライブ待機'))
        self.summary.setText('  ·  '.join(parts))

    def collect_spec(self) -> dict[str, Any]:
        spec = {
            'url': self.url.text().strip(),
            'mode': self.mode.value(),
            'quality': 'custom' if self.custom_format else self.quality.currentData(),
            'format': self.custom_format,
            'container': self.container.currentData(),
            'audio_codec': self.audio_codec.currentData(),
            'audio_quality': self.audio_quality.currentData(),
            'out_dir': self.out_dir.text().strip(),
            'template': self.template.text().strip(),
            'playlist': self.playlist.isChecked(),
            'range_start': self.range_start.text().strip() if self.range_on.isChecked() else '',
            'range_end': self.range_end.text().strip() if self.range_on.isChecked() else '',
            'precise_cut': self.precise.isChecked(),
            'subs': self.subs.isChecked(),
            'sub_langs': self.sub_langs.text().strip(),
            'auto_subs': self.auto_subs.isChecked(),
            'embed_subs': self.embed_subs.isChecked(),
            'chapters': self.chapters.isChecked(),
            'embed_thumbnail': self.embed_thumb.isChecked(),
            'metadata': self.metadata.isChecked(),
            'wait_live': self.wait_live.isChecked(),
            'wait_retry_sec': self.wait_interval.value(),
            'live_from_start': self.live_from_start.isChecked(),
            'cookies_browser': self.cookie_browser.currentData(),
            'cookies_profile': self.cookie_profile.text().strip(),
            'cookies_file': self.cookie_file.text().strip(),
            'rate_limit': self.rate.text().strip(),
        }
        if spec['mode'] == 'audio' and self.custom_format:
            spec['quality'], spec['format'] = 'custom', self.custom_format
        return spec

    def apply_spec(self, spec: dict[str, Any], *, include_url: bool = True) -> None:
        s = normalize_job(spec)
        if include_url:
            self.url.setText(s['url'])
        self.mode.set_value(s['mode'])
        _set_combo(self.quality, s['quality'] if s['quality'] != 'custom' else 'best')
        _set_combo(self.container, s['container'])
        _set_combo(self.audio_codec, s['audio_codec'])
        _set_combo(self.audio_quality, str(s['audio_quality']))
        self.template.setText(s['template'])
        self.playlist.setChecked(bool(s['playlist']))
        self.range_on.setChecked(bool(s['range_start'] or s['range_end']))
        self.range_start.setText(s['range_start'])
        self.range_end.setText(s['range_end'])
        self.precise.setChecked(bool(s['precise_cut']))
        self.subs.setChecked(bool(s['subs']))
        self.sub_langs.setText(s['sub_langs'])
        self.auto_subs.setChecked(bool(s['auto_subs']))
        self.embed_subs.setChecked(bool(s['embed_subs']))
        self.chapters.setChecked(bool(s['chapters']))
        self.embed_thumb.setChecked(bool(s['embed_thumbnail']))
        self.metadata.setChecked(bool(s['metadata']))
        self.wait_live.setChecked(bool(s['wait_live']))
        self.wait_interval.setValue(int(s['wait_retry_sec'] or 60))
        self.live_from_start.setChecked(bool(s['live_from_start']))
        self.rate.setText(s['rate_limit'])
        if include_url:
            if s['out_dir']:
                self.out_dir.setText(s['out_dir'])
            _set_combo(self.cookie_browser, s['cookies_browser'])
        self._set_custom(s['format'] if s['quality'] == 'custom' else '')

    # ---------- プロファイル ----------
    def _reload_profiles(self, select: str = '') -> None:
        self.profile.blockSignals(True)
        self.profile.clear()
        for pid in self.settings.profile_ids():
            self.profile.addItem(self.settings.profile_label(pid), pid)
        if select:
            _set_combo(self.profile, select)
        self.profile.blockSignals(False)

    def _apply_profile(self, pid: str) -> None:
        prof = self.settings.get_profile(pid)
        if not prof and not self.settings.is_builtin(pid):
            pid = self.settings.profile_ids()[0]
            prof = self.settings.get_profile(pid)
        base = {k: v for k, v in JOB_DEFAULTS.items()}
        base['template'] = self.settings['template']
        base.update(prof)
        self.apply_spec(base, include_url=False)
        _set_combo(self.profile, pid)
        self.settings['last_profile'] = pid
        self._sync_enabled()

    def _save_profile(self) -> None:
        current = self.profile.currentData() or ''
        default = '' if self.settings.is_builtin(current) else current
        name, ok = QInputDialog.getText(self, tr('プロファイルを保存'), tr('プロファイル名:'), text=default)
        if not ok or not name.strip():
            return
        try:
            pid = self.settings.save_profile(name, normalize_job(self.collect_spec()))
        except ValueError as e:
            QMessageBox.warning(self, tr('プロファイル'), str(e))
            return
        self._reload_profiles(pid)
        self.settings['last_profile'] = pid
        self._sync_enabled()
        self.status_message.emit(tr('プロファイル「{name}」を保存しました', name=name.strip()))

    def _delete_profile(self) -> None:
        pid = self.profile.currentData() or ''
        if not pid or self.settings.is_builtin(pid):
            return
        if QMessageBox.question(self, tr('プロファイル'), tr('「{name}」を削除しますか?', name=pid)) != QMessageBox.StandardButton.Yes:
            return
        self.settings.delete_profile(pid)
        self._reload_profiles()
        self._apply_profile(self.profile.currentData())

    # ---------- 操作 ----------
    def set_url(self, url: str) -> None:
        self.url.setText(url.strip())
        self.url.setFocus()

    def _paste(self) -> None:
        self.set_url(QGuiApplication.clipboard().text().strip().splitlines()[0] if QGuiApplication.clipboard().text().strip() else '')

    def _on_url_changed(self, _text: str) -> None:
        if self.info is not None:
            self.info = None
            self.info_card.hide()
            self._set_custom('')

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr('保存先'), self.out_dir.text())
        if d:
            self.out_dir.setText(d)

    def _pick_cookie_file(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, 'cookies.txt', '', tr('Cookie ファイル (*.txt);;すべて (*)'))
        if f:
            self.cookie_file.setText(f)

    def _set_custom(self, fmt: str) -> None:
        self.custom_format = fmt
        self.custom_lb.setText(tr('形式: {fmt}', fmt=fmt))
        self.custom_lb.setVisible(bool(fmt))
        self.custom_clear.setVisible(bool(fmt))
        self._sync_enabled()

    def _pick_formats(self) -> None:
        if not self.info or not self.info.get('formats'):
            return
        dlg = FormatDialog(self.info['formats'], self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_format:
            self._set_custom(dlg.result_format)

    def _spec_with_env(self) -> dict[str, Any]:
        spec = self.collect_spec()
        spec.update(self.env())
        return spec

    def analyze(self) -> None:
        spec = self._spec_with_env()
        try:
            validate_job(normalize_job(spec))
        except JobError as e:
            self._show_probe(str(e), error=True)
            return
        if self.probe and self.probe.is_running():
            # 古い解析の終了通知が新しい解析中のボタン表示を戻さないよう、先に切り離す
            self.probe.message.disconnect()
            self.probe.finished.disconnect()
            self.probe.kill()
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText(tr('解析中…'))
        self._show_probe(tr('情報を取得しています…'))
        self.probe = WorkerProcess(self)
        self.probe.message.connect(self._on_probe_msg)
        self.probe.finished.connect(self._on_probe_done)
        self._probe_error = ''
        self._probe_url = spec['url']
        self.probe.start('probe', spec)

    def _on_probe_msg(self, m: dict) -> None:
        if m.get('t') == 'result' and 'info' in m:
            self._fill_info(m['info'])
        elif m.get('t') == 'error':
            self._probe_error = str(m.get('msg') or '')
        elif m.get('t') == 'log' and m.get('level') == 'error' and not self._probe_error:
            self._probe_error = str(m.get('msg') or '')

    def _on_probe_done(self, code: int) -> None:
        self.analyze_btn.setEnabled(True)
        self.analyze_btn.setText(tr('解析'))
        if code != 0 and code != -1:
            raw = self._probe_error or (self.probe.stderr_tail[-1] if self.probe and self.probe.stderr_tail else '')
            summary, hint = errors.explain(raw)
            self._show_probe(f'{summary} — {hint}', error=True)
            self.probe_status.setToolTip(raw)
        elif code == 0:
            self.probe_status.hide()

    def _show_probe(self, text: str, *, error: bool = False) -> None:
        self.probe_status.setObjectName('errText' if error else 'muted')
        restyle(self.probe_status)
        self.probe_status.setText(text)
        self.probe_status.setToolTip('')
        self.probe_status.show()

    def _fill_info(self, info: dict) -> None:
        if self.url.text().strip() != getattr(self, '_probe_url', ''):
            return  # 解析中に URL が変わった
        self.info = info
        self.title_lb.setText(info.get('title') or tr('(無題)'))
        bits = [b for b in (info.get('uploader') or info.get('channel'), info.get('extractor_key')) if b]
        if info.get('duration'):
            bits.append(format_seconds(info['duration']))
        if info.get('upload_date'):
            d = str(info['upload_date'])
            bits.append(f'{d[:4]}/{d[4:6]}/{d[6:]}')
        self.meta_lb.setText('  ·  '.join(bits))
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        chips = []
        status = info.get('live_status')
        if info.get('_type') == 'playlist':
            chips.append(tr('プレイリスト {count} 件', count=info.get('playlist_count') or '?'))
        if status == 'is_live':
            chips.append(tr('● ライブ配信中'))
        elif status == 'is_upcoming':
            ts = info.get('release_timestamp')
            chips.append(tr('配信予定') + (f' {time.strftime("%m/%d %H:%M", time.localtime(ts))}' if ts else ''))
            self.wait_live.setChecked(True)
        if info.get('subtitles'):
            chips.append(tr('字幕 {count} 言語', count=len(info['subtitles'])))
        if info.get('auto_captions'):
            chips.append(tr('自動字幕あり'))
        if info.get('chapters'):
            chips.append(tr('チャプター {count}', count=info['chapters']))
        if info.get('formats'):
            chips.append(tr('形式 {count} 種', count=len(info['formats'])))
        for text in chips:
            self.chips.addWidget(label(text, 'chip'))
        self.chips.addStretch(1)
        langs = info.get('subtitles') or []
        self.subs_hint.setText(tr('この動画の字幕: ') + ', '.join(langs[:30]) + (' …' if len(langs) > 30 else '')
                               if langs else tr('手動字幕はありません(自動生成字幕のみの可能性があります)'))
        self.subs_hint.show()
        self.formats_btn.setEnabled(bool(info.get('formats')))
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText('')
        if info.get('thumbnail'):
            req = QNetworkRequest(QUrl(info['thumbnail']))
            req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
            self.net.get(req)
        self.info_card.show()
        self._sync_enabled()

    def _on_thumb(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError or not self.info:
            return
        pm = QPixmap()
        if pm.loadFromData(bytes(reply.readAll())):
            self.thumb.setPixmap(pm.scaled(self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation).copy(0, 0, 256, 144))

    def current_thumbnail(self) -> str:
        return (self.info or {}).get('thumbnail') or ''

    def submit(self) -> None:
        spec = self._spec_with_env()
        try:
            validate_job(normalize_job(spec))
        except JobError as e:
            self._show_probe(str(e), error=True)
            return
        start_at = self.schedule_at.dateTime().toSecsSinceEpoch() if self.schedule_on.isChecked() else None
        if start_at and start_at <= time.time():
            self._show_probe(tr('予約時刻が過去です'), error=True)
            return
        title = (self.info or {}).get('title') or spec['url']
        # 実行環境(ffmpeg/JS)は実行直前に最新を入れ直すので、キューには保存しない
        for k in ('ffmpeg_location', 'js_runtime'):
            spec.pop(k, None)
        self.enqueue.emit(spec, title, self.current_thumbnail(), start_at)
        self.settings['download_dir'] = spec['out_dir'] or self.settings['download_dir']
        self.url.clear()
        self.probe_status.hide()
        self.schedule_on.setChecked(False)
