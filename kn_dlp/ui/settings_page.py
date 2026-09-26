"""設定画面: 既定値・外部ツール・yt-dlp 更新(F)。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QScrollArea,
                               QFrame, QSpinBox, QVBoxLayout, QWidget)

from .. import APP_DISPLAY_NAME, __version__, i18n, options, paths, plugins, tools, updater
from ..settings import LANGUAGES, Settings
from .procs import BgTask, WorkerProcess
from . import theme
from .widgets import Card, Segmented, button, human_size, label, open_path, restyle, reveal
from ..i18n import tr


def _row(title: str, *widgets, stretch: bool = True) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(8)
    lb = label(title, 'muted')
    lb.setMinimumWidth(110)
    lay.addWidget(lb)
    for w in widgets:
        lay.addWidget(w)
    if stretch:
        lay.addStretch(1)
    return lay


class SettingsPage(QWidget):
    tools_changed = Signal()
    ytdlp_changed = Signal(str, bool)       # 現在の版, 更新あり

    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('page')
        self.settings = settings
        self.latest: dict | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        inner.setObjectName('page')
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(32, 26, 32, 26)
        lay.setSpacing(14)
        lay.addWidget(label(tr('設定'), 'h1'))

        # 表示
        c = Card(tr('表示'))
        self.theme_seg = Segmented([('system', tr('システムに合わせる')), ('dark', tr('ダーク')), ('light', tr('ライト'))])
        self.theme_seg.set_value(settings['theme'])
        self.theme_seg.changed.connect(self._set_theme)
        c.body.addLayout(_row(tr('テーマ'), self.theme_seg))
        self.lang = QComboBox()
        for code in LANGUAGES:
            self.lang.addItem(i18n.LANG_NAMES.get(code) or tr('OS に合わせる'), code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(settings['language'])))
        self.lang.currentIndexChanged.connect(self._set_language)
        c.body.addLayout(_row(tr('言語'), self.lang))
        self.lang_note = label(tr('言語の変更はアプリの再起動後に反映されます'), 'warnText')
        self.lang_note.hide()
        c.body.addWidget(self.lang_note)
        lay.addWidget(c)

        # yt-dlp
        c = Card(tr('yt-dlp 本体'), tr('サイト側の仕様変更に追従するため、こまめな更新を推奨'))
        self.ver_lb = label('', 'title')
        self.src_lb = label('', 'faint')
        c.body.addWidget(self.ver_lb)
        c.body.addWidget(self.src_lb)
        self.upd_lb = label('', 'muted', wrap=True)
        c.body.addWidget(self.upd_lb)
        br = QHBoxLayout()
        self.check_btn = button(tr('更新を確認'))
        self.check_btn.clicked.connect(self.check_update)
        self.update_btn = button(tr('更新する'), 'primary')
        self.update_btn.clicked.connect(self.do_update)
        self.update_btn.hide()
        self.rollback_btn = button(tr('1つ前の版に戻す'), 'ghost')
        self.rollback_btn.clicked.connect(self._rollback)
        self.reset_btn = button(tr('同梱版に戻す'), 'ghost')
        self.reset_btn.clicked.connect(self._reset)
        for b in (self.check_btn, self.update_btn, self.rollback_btn, self.reset_btn):
            br.addWidget(b)
        br.addStretch(1)
        c.body.addLayout(br)
        self.auto_check = QCheckBox(tr('起動時に更新を確認する'))
        self.auto_check.setChecked(settings['check_update_on_start'])
        self.auto_check.toggled.connect(lambda v: self._set('check_update_on_start', v))
        c.body.addWidget(self.auto_check)
        lay.addWidget(c)

        # 外部ツール
        c = Card(tr('外部ツール'))
        self.ff_status = label('')
        c.body.addWidget(self.ff_status)
        self.ff_path = QLineEdit(settings['ffmpeg_path'])
        self.ff_path.setPlaceholderText(tr('空欄 = 自動検出'))
        self.ff_path.editingFinished.connect(lambda: (self._set('ffmpeg_path', self.ff_path.text().strip()), self.refresh_tools()))
        pick = button(tr('参照'), 'ghost')
        pick.clicked.connect(self._pick_ffmpeg)
        self.ff_get = button(tr('ffmpeg を自動取得'))
        self.ff_get.setToolTip(tr('yt-dlp 公式の FFmpeg ビルド (GPL・約 85MB) をデータフォルダへ取得します'))
        self.ff_get.clicked.connect(self._install_ffmpeg)
        c.body.addLayout(_row('ffmpeg', self.ff_path, pick, self.ff_get, stretch=False))
        c.body.addWidget(label(tr('結合・音声変換・切り出し・埋め込みに必要です。'), 'faint'))
        self.js_status = label('')
        c.body.addWidget(self.js_status)
        self.js_pref = QComboBox()
        for key, text in (('', tr('自動 (deno → node → bun)')), ('deno', 'deno'), ('node', 'Node.js'), ('bun', 'Bun')):
            self.js_pref.addItem(text, key)
        self.js_pref.setCurrentIndex(max(0, self.js_pref.findData(settings['js_runtime'])))
        self.js_pref.currentIndexChanged.connect(lambda _: (self._set('js_runtime', self.js_pref.currentData()), self.refresh_tools()))
        c.body.addLayout(_row(tr('JS ランタイム'), self.js_pref))
        c.body.addWidget(label(tr('YouTube の署名解読に必要です。無いと一部の形式が取れません。'), 'faint'))
        lay.addWidget(c)

        # プラグイン
        c = Card(tr('プラグイン'), tr('yt-dlp のプラグインで、サイト対応や後処理を追加できます'))
        self.plug_seg = Segmented([('all', tr('すべて')), ('app', tr('kn_dlp のみ')), ('off', tr('オフ'))])
        self.plug_seg.set_value(settings['plugins'])
        self.plug_seg.changed.connect(self._set_plugin_mode)
        c.body.addLayout(_row(tr('読み込む場所'), self.plug_seg))
        self.plug_scope = label('', 'faint', wrap=True)
        c.body.addWidget(self.plug_scope)
        self.plug_status = label('', 'muted', wrap=True)
        c.body.addWidget(self.plug_status)
        self.plug_list = QVBoxLayout()
        self.plug_list.setSpacing(4)
        c.body.addLayout(self.plug_list)
        pr = QHBoxLayout()
        pod = button(tr('プラグインフォルダを開く'), 'ghost')
        pod.clicked.connect(self._open_plugins_dir)
        self.plug_reload = button(tr('再読み込み'), 'ghost')
        self.plug_reload.clicked.connect(self.refresh_plugins)
        pr.addWidget(pod)
        pr.addWidget(self.plug_reload)
        pr.addStretch(1)
        c.body.addLayout(pr)
        c.body.addWidget(label(tr('プラグインはあなたの権限で動く Python コードです。信頼できるものだけを置いてください。'
                               'yt-dlp の更新で動かなくなることがあります。'), 'warnText', wrap=True))
        lay.addWidget(c)
        self._plug_proc: WorkerProcess | None = None
        self._plug_loaded = False
        self._update_plugin_scope()

        # 既定値
        c = Card(tr('既定値'))
        self.dir = QLineEdit(settings['download_dir'])
        self.dir.editingFinished.connect(lambda: self._set('download_dir', self.dir.text().strip()))
        pd = button(tr('参照'), 'ghost')
        pd.clicked.connect(self._pick_dir)
        c.body.addLayout(_row(tr('保存先'), self.dir, pd, stretch=False))
        self.tmpl = QLineEdit(settings['template'])
        self.tmpl.editingFinished.connect(lambda: self._set('template', self.tmpl.text().strip() or settings['template']))
        c.body.addLayout(_row(tr('ファイル名'), self.tmpl, stretch=False))
        c.body.addWidget(label(tr('例: %(uploader)s/%(title)s.%(ext)s — 使える項目は yt-dlp の README「OUTPUT TEMPLATE」を参照'), 'faint'))
        self.conc = QSpinBox()
        self.conc.setRange(1, 8)
        self.conc.setValue(settings['concurrency'])
        c.body.addLayout(_row(tr('同時実行数'), self.conc))
        lay.addWidget(c)

        # 情報
        c = Card(tr('このアプリについて'))
        c.body.addWidget(label(f'{APP_DISPLAY_NAME} {__version__}', 'title'))
        c.body.addWidget(label(tr('yt-dlp (Unlicense) の GUI です。本アプリは GPL-3.0 で配布しています。'
                               'ダウンロードする内容の権利と各サイトの利用規約は、利用者ご自身で確認してください。'), 'muted', wrap=True))
        dr = QHBoxLayout()
        od = button(tr('データフォルダを開く'), 'ghost')
        od.clicked.connect(lambda: reveal(str(paths.data_dir() / 'settings.json')))
        dr.addWidget(od)
        dr.addStretch(1)
        c.body.addLayout(dr)
        lay.addWidget(c)
        lay.addStretch(1)
        self.refresh_tools()
        self.refresh_version()

    def _set_theme(self, value: str) -> None:
        self._set('theme', value)
        theme.apply(value, i18n.current())

    def _set_language(self, _index: int) -> None:
        code = self.lang.currentData()
        self._set('language', code)
        self.lang_note.setVisible((i18n.normalize(code) if code else i18n.system_language()) != i18n.current())

    # ---- プラグイン ----
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._plug_loaded:   # 一覧はワーカーの起動が要るので、初めて開いたときに取る
            self._plug_loaded = True
            self.refresh_plugins()

    def _set_plugin_mode(self, mode: str) -> None:
        self._set('plugins', plugins.set_mode(mode))
        self._update_plugin_scope()
        self.refresh_plugins()

    def _update_plugin_scope(self) -> None:
        own = str(plugins.plugins_dir())
        self.plug_scope.setText({
            'all': tr('kn_dlp 専用フォルダ ({path}) と、yt-dlp 本体の既定の場所 (%APPDATA%\\yt-dlp\\plugins など) から読み込みます', path=own),
            'app': tr('kn_dlp 専用フォルダ ({path}) だけから読み込みます', path=own),
            'off': tr('プラグインを読み込みません'),
        }[plugins.current_mode()])

    def _open_plugins_dir(self) -> None:
        d = plugins.ensure_dir()
        if d is None:
            QMessageBox.warning(self, tr('プラグイン'), tr('フォルダを作成できませんでした: {path}', path=plugins.plugins_dir()))
            return
        open_path(str(d))

    def refresh_plugins(self) -> None:
        if self._plug_proc is not None:
            self._plug_proc.message.disconnect()
            self._plug_proc.finished.disconnect()
            self._plug_proc.kill()
        self.plug_reload.setEnabled(False)
        self.plug_status.setText(tr('読み込み中…'))
        self._clear_plugin_list()
        proc = WorkerProcess(self)
        self._plug_proc = proc
        result: dict = {}
        proc.message.connect(lambda m: result.update(m) if m.get('t') in ('result', 'error') else None)
        proc.finished.connect(lambda _code: self._on_plugins(proc, result))
        proc.start('plugins')

    def _pp_controls(self, name: str) -> QWidget:
        """後処理プラグイン1つ分の「実行する / 時点 / 引数」。変更はその場で保存する。"""
        cfg = self.settings.plugin_pp(name)
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(16, 0, 0, 0)
        row.setSpacing(8)
        on = QCheckBox(tr('実行する'))
        on.setChecked(cfg['enabled'])
        when = QComboBox()
        for key, text in (('pre_process', tr('解析の直後')), ('before_dl', tr('ダウンロード前')),
                          ('post_process', tr('ダウンロード後 (既定)')), ('after_move', tr('保存先へ移動した後')),
                          ('playlist', tr('再生リストの最後'))):
            when.addItem(text, key)
        when.setCurrentIndex(max(0, when.findData(cfg['when'])))
        args = QLineEdit(cfg['args'])
        args.setPlaceholderText(tr('引数 (例: key=value;key2=value2)'))
        err = label('', 'errText')
        err.hide()

        def save_args() -> None:
            try:
                options.parse_pp_args(args.text())
            except options.JobError as e:
                err.setText(str(e))
                err.show()
                return
            err.hide()
            self.settings.set_plugin_pp(name, args=args.text().strip())

        on.toggled.connect(lambda v: self.settings.set_plugin_pp(name, enabled=bool(v)))
        when.currentIndexChanged.connect(lambda _i: self.settings.set_plugin_pp(name, when=when.currentData()))
        args.editingFinished.connect(save_args)
        row.addWidget(on)
        row.addWidget(when)
        row.addWidget(args, 1)
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(box)
        col.addWidget(err)
        return wrap

    def _clear_plugin_list(self) -> None:
        while self.plug_list.count():
            w = self.plug_list.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _on_plugins(self, proc: WorkerProcess, result: dict) -> None:
        if proc is not self._plug_proc:
            return
        self._plug_proc = None
        proc.deleteLater()
        self.plug_reload.setEnabled(True)
        if result.get('t') != 'result':
            msg = result.get('msg') or (proc.stderr_tail[-1] if proc.stderr_tail else '')
            self._status(self.plug_status, tr('一覧を取得できませんでした: {e}', e=msg), 'errText')
            return
        items, errors = result.get('items') or [], result.get('errors') or []
        kinds = {'extractor': tr('サイト対応'), 'postprocessor': tr('後処理'), 'override': tr('既存サイトの上書き')}
        if result.get('mode') == 'off':
            text = tr('オフのため読み込んでいません')
        elif items or errors:
            text = tr('{count} 件のプラグインを読み込みました', count=len(items))
        else:
            text = tr('プラグインはありません')
        self._status(self.plug_status, text, 'muted')
        dirs = result.get('dirs') or []
        self.plug_status.setToolTip(tr('探索した場所:') + '\n' + '\n'.join(dirs) if dirs else '')
        has_pp = False
        for it in items:
            lb = label(f"{kinds.get(it.get('kind'), it.get('kind'))}  ·  {it.get('name')}", wrap=True)
            lb.setToolTip(f"{it.get('class')}\n{it.get('file')}")
            self.plug_list.addWidget(lb)
            if it.get('kind') == 'postprocessor' and str(it.get('class', '')).endswith('PP'):
                has_pp = True
                self.plug_list.addWidget(self._pp_controls(str(it['class'])[:-2]))
            self.plug_list.addWidget(label(str(it.get('file') or ''), 'faint', wrap=True))
        if has_pp:
            self.plug_list.addWidget(label(tr('後処理のプラグインは「実行する」にしたものだけが動きます(同じ時点の標準の後処理より後)。'
                                              '引数は key=value を ; で区切ります (yt-dlp の --use-postprocessor と同じ書式)。'),
                                           'faint', wrap=True))
        for err in errors:
            self.plug_list.addWidget(label(tr('✕ 読み込み失敗: {module} — {error}', **err), 'errText', wrap=True))

    def _set(self, key: str, value) -> None:
        self.settings[key] = value
        self.settings.save()

    # ---- ツール ----
    def env(self) -> dict:
        ff = tools.find_ffmpeg(self.settings['ffmpeg_path'])
        pps = self.settings.enabled_plugin_pps() if plugins.current_mode() != 'off' else []
        return {'ffmpeg_location': ff or '', 'js_runtime': tools.find_js_runtime(self.settings['js_runtime']),
                'plugin_pps': pps}

    def refresh_tools(self) -> None:
        e = self.env()
        if e['ffmpeg_location']:
            self._status(self.ff_status, f'✓ ffmpeg: {e["ffmpeg_location"]}', 'okText')
        else:
            self._status(self.ff_status, tr('✕ ffmpeg が見つかりません'), 'errText')
        rt = e['js_runtime']
        if rt:
            self._status(self.js_status, f'✓ {rt["name"]}: {rt["path"]}', 'okText')
        else:
            self._status(self.js_status, tr('! JS ランタイムが見つかりません (deno か Node.js を導入してください)'), 'warnText')
        self.tools_changed.emit()

    @staticmethod
    def _status(lb, text: str, name: str) -> None:
        lb.setText(text)
        lb.setObjectName(name)
        lb.setWordWrap(True)
        restyle(lb)

    def _pick_ffmpeg(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, 'ffmpeg', '', tr('ffmpeg (ffmpeg.exe ffmpeg);;すべて (*)'))
        if f:
            self.ff_path.setText(f)
            self._set('ffmpeg_path', f)
            self.refresh_tools()

    def _pick_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr('保存先'), self.dir.text())
        if d:
            self.dir.setText(d)
            self._set('download_dir', d)

    def _install_ffmpeg(self) -> None:
        self.ff_get.setEnabled(False)
        self.ff_get.setText(tr('取得中…'))
        task = BgTask(updater.install_ffmpeg, with_progress=True)
        task.progress.connect(lambda r, t: self.ff_get.setText(tr('取得中… {size}', size=human_size(r)) + (f' / {human_size(t)}' if t else '')))
        task.done.connect(lambda _: self._ff_done(''))
        task.failed.connect(self._ff_done)
        task.start()

    def _ff_done(self, err: str) -> None:
        self.ff_get.setEnabled(True)
        self.ff_get.setText(tr('ffmpeg を自動取得'))
        if err:
            QMessageBox.warning(self, 'ffmpeg', err)   # 失敗時は利用者が指定したパスを消さない
        else:
            self.ff_path.setText('')
            self._set('ffmpeg_path', '')
        self.refresh_tools()

    # ---- yt-dlp ----
    def refresh_version(self) -> None:
        ver, src = updater.current_version()
        self.current = ver
        src_text = {'updated': tr('更新版 (データフォルダ)'), 'bundled': tr('同梱版'), 'site-packages': tr('開発環境 (pip)'),
                    'none': tr('見つかりません')}[src]
        self.ver_lb.setText(f'yt-dlp {ver or "—"}')
        self.src_lb.setText(src_text)
        self.rollback_btn.setVisible(updater.backup_version() is not None)
        self.reset_btn.setVisible(src == 'updated')
        has_update = bool(self.latest and updater.is_newer(self.latest['version'], ver))
        self.update_btn.setVisible(has_update)
        if self.latest:
            date = self.latest['published_at'][:10].replace('-', '/')
            self.upd_lb.setText(tr('最新版 {version} ({date} 公開) が利用できます', version=self.latest['version'], date=date) if has_update
                                else tr('最新版です (最新 {version} · {date} 公開)', version=self.latest['version'], date=date))
        self.ytdlp_changed.emit(ver, has_update)

    def check_update(self, silent: bool = False) -> None:
        self.check_btn.setEnabled(False)
        if not silent:
            self.upd_lb.setText(tr('確認しています…'))
        task = BgTask(updater.fetch_latest)
        task.done.connect(self._on_latest)
        task.failed.connect(lambda e: (self.check_btn.setEnabled(True), self.upd_lb.setText(tr('確認できませんでした: {e}', e=e))))
        task.start()

    def _on_latest(self, rel: dict) -> None:
        self.check_btn.setEnabled(True)
        self.latest = rel
        self.refresh_version()

    def do_update(self) -> None:
        if not self.latest:
            return
        self.update_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        rel = self.latest
        task = BgTask(lambda cb: updater.install(rel, cb), with_progress=True)
        task.progress.connect(lambda r, t: self.upd_lb.setText(tr('ダウンロード中… {size}', size=human_size(r)) + (f' / {human_size(t)}' if t else '')))
        task.done.connect(self._on_updated)
        task.failed.connect(self._on_update_failed)
        task.start()

    def _on_updated(self, ver: str) -> None:
        self.update_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self.refresh_version()
        self.upd_lb.setText(tr('yt-dlp {ver} に更新しました(SHA-256 検証済み)。次のダウンロードから使われます。', ver=ver))

    def _on_update_failed(self, err: str) -> None:
        self.update_btn.setEnabled(True)
        self.check_btn.setEnabled(True)
        self.upd_lb.setText(tr('更新できませんでした: {err}', err=err))

    def _rollback(self) -> None:
        try:
            ver = updater.rollback()
        except (updater.UpdateError, OSError) as e:
            QMessageBox.warning(self, 'yt-dlp', str(e))
            return
        self.refresh_version()
        self.upd_lb.setText(tr('{ver} に戻しました', ver=ver))

    def _reset(self) -> None:
        if QMessageBox.question(self, 'yt-dlp', tr('更新版を削除して同梱版に戻しますか?')) == QMessageBox.StandardButton.Yes:
            try:
                updater.reset_to_bundled()
            except OSError as e:
                QMessageBox.warning(self, 'yt-dlp', tr('削除できませんでした(ダウンロード中は使用中の可能性があります): {e}', e=e))
            self.refresh_version()
