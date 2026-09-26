"""ファイル名テンプレートの入力欄: 雛形の選択 + 入力 + 保存名のプレビュー。

プレビューは yt-dlp 自身(ワーカーの filename 要求)で展開するので、実際の保存名と食い違わない。
入力のたびにワーカーを起こさないよう、止まってから少し待って1回だけ作る。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ..i18n import tr
from ..options import TEMPLATE_PRESETS
from .procs import WorkerProcess
from .widgets import label, restyle

# (ジョブ指定, 解析済みの情報 or None) を返す関数
Context = Callable[[], tuple[dict, dict | None]]


class TemplateEdit(QWidget):
    edited = Signal(str)            # 雛形の選択か入力の確定で、新しい値

    def __init__(self, context: Context, *, stacked: bool = False, parent: QWidget | None = None):
        """stacked=True で入力欄を1行に取り、雛形の選択をその下に置く(狭いカード用)。"""
        super().__init__(parent)
        self.context = context
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.preset = QComboBox()
        self.preset.addItem(tr('カスタム'), '')
        for name, tmpl in TEMPLATE_PRESETS:
            self.preset.addItem(tr(name), tmpl)
            self.preset.setItemData(self.preset.count() - 1, tmpl, Qt.ItemDataRole.ToolTipRole)
        # 一番長い雛形名に合わせて幅を取ると、狭い画面で入力欄が潰れる(一覧を開けば全文が見える)
        self.preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(9)
        self.preset.view().setMinimumWidth(320)
        self.edit = QLineEdit()
        self.edit.setToolTip(tr('yt-dlp の出力テンプレート。使える項目は yt-dlp の README「OUTPUT TEMPLATE」を参照'))
        if stacked:
            lay.addWidget(self.edit)
            row.addWidget(self.preset)
            row.addStretch(1)
        else:
            row.addWidget(self.preset)
            row.addWidget(self.edit, 1)
        lay.addLayout(row)
        self.preview = label('', 'faint', wrap=True)
        lay.addWidget(self.preview)
        self._proc: WorkerProcess | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._run_preview)
        self.preset.activated.connect(self._on_preset)
        self.edit.textChanged.connect(lambda _t: (self._sync_preset(), self.schedule_preview()))
        self.edit.editingFinished.connect(lambda: self.edited.emit(self.text()))

    # QLineEdit と同じ使い方ができるように
    def text(self) -> str:
        return self.edit.text()

    def setText(self, text: str) -> None:
        self.edit.setText(text)
        self.edit.setCursorPosition(0)   # 長いテンプレートは先頭から見せる

    def _on_preset(self, index: int) -> None:
        tmpl = self.preset.itemData(index)
        if tmpl:
            self.setText(tmpl)
            self.edited.emit(tmpl)

    def _sync_preset(self) -> None:
        idx = self.preset.findData(self.edit.text().strip())
        self.preset.setCurrentIndex(idx if idx > 0 else 0)

    def schedule_preview(self) -> None:
        self._timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.schedule_preview()

    def _run_preview(self) -> None:
        if not self.isVisible():
            return   # 見えていないときはワーカーを起こさない(表示時に作り直す)
        if self._proc is not None:
            self._proc.message.disconnect()
            self._proc.finished.disconnect()
            self._proc.kill()
        spec, info = self.context()
        job = {**spec, 'template': self.text().strip()}
        if info:   # 形式一覧や再生リストの中身は名前に使わないので送らない
            job['preview_info'] = {k: v for k, v in info.items() if not isinstance(v, (list, dict))}
        proc = WorkerProcess(self)
        self._proc = proc
        result: dict = {}
        proc.message.connect(lambda m: result.update(m) if m.get('t') in ('result', 'error') else None)
        proc.finished.connect(lambda _code: self._on_preview(proc, result))
        proc.start('filename', job)

    def _on_preview(self, proc: WorkerProcess, result: dict) -> None:
        if proc is not self._proc:
            return
        self._proc = None
        proc.deleteLater()
        if result.get('t') == 'result' and result.get('name'):
            text = tr('保存名の例: {name}', name=result['name']) if result.get('sample') else tr('保存名: {name}', name=result['name'])
            self._show(text, 'faint')
        else:
            self._show(tr('保存名を作れません: {e}', e=result.get('msg') or ''), 'errText')

    def _show(self, text: str, name: str) -> None:
        self.preview.setText(text)
        self.preview.setObjectName(name)
        restyle(self.preview)
