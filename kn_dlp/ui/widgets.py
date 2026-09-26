"""共通の画面部品と小道具。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)


def human_size(n: float | int | None) -> str:
    if not n:
        return '—'
    n = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'


def human_speed(bps: float | None) -> str:
    return f'{human_size(bps)}/s' if bps else ''


def reveal(path: str | None) -> None:
    """エクスプローラでファイルを選択状態で開く。無ければ親フォルダ。"""
    if not path:
        return
    p = Path(path)
    if os.name == 'nt' and p.exists():
        subprocess.Popen(['explorer', '/select,', str(p)])
        return
    folder = p if p.is_dir() else p.parent
    if folder.exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def open_path(path: str | None) -> None:
    if path and Path(path).exists():
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def label(text: str = '', name: str = '', *, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    lb.setWordWrap(wrap)
    return lb


def button(text: str, name: str = '', *, tip: str = '') -> QPushButton:
    b = QPushButton(text)
    if name:
        b.setObjectName(name)
    if tip:
        b.setToolTip(tip)
    return b


class Card(QFrame):
    def __init__(self, title: str = '', subtitle: str = '', parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName('card')
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(18, 14, 18, 16)
        self.outer.setSpacing(10)
        if title:
            head = QHBoxLayout()
            head.setSpacing(8)
            head.addWidget(label(title, 'h2'))
            if subtitle:
                head.addWidget(label(subtitle, 'faint'))
            head.addStretch(1)
            self.head = head
            self.outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(9)
        self.outer.addLayout(self.body)


class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for i, (key, text) in enumerate(options):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setObjectName('seg')
            b.setProperty('class', '')
            if i == 0:
                b.setStyleSheet('border-top-left-radius:8px;border-bottom-left-radius:8px;')
            if i == len(options) - 1:
                b.setStyleSheet('border-top-right-radius:8px;border-bottom-right-radius:8px;')
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def value(self) -> str:
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return next(iter(self.buttons))

    def set_value(self, key: str) -> None:
        if key in self.buttons:
            self.buttons[key].setChecked(True)


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName('sep')
    return f


def restyle(w: QWidget) -> None:
    """動的プロパティ変更後に QSS を再適用する。"""
    w.style().unpolish(w)
    w.style().polish(w)


def is_windows() -> bool:
    return sys.platform.startswith('win')
