"""配色トークンと QSS。色はここ以外に直書きしない。"""
from __future__ import annotations

import functools

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

PALETTES: dict[str, dict[str, str]] = {
    'dark': {
        'bg': '#0b0d12',
        'side': '#0f1218',
        'surface': '#141821',
        'surface2': '#1a1f2a',
        'surface3': '#222836',
        'border': '#262d3b',
        'text': '#e7eaf0',
        'muted': '#8a93a6',
        'faint': '#5c6477',
        'accent': '#22d3ee',
        'accent_hover': '#67e8f9',
        'accent_press': '#0891b2',
        'on_accent': '#04141a',
        'selection': '#0891b2',
        'ok': '#34d399',
        'warn': '#fbbf24',
        'danger': '#f87171',
        'info': '#818cf8',
    },
    'light': {
        'bg': '#f4f6f9',
        'side': '#eaeef3',
        'surface': '#ffffff',
        'surface2': '#f5f7fa',
        'surface3': '#e5e9ef',
        'border': '#d5dbe4',
        'text': '#161a22',
        'muted': '#5a6375',
        'faint': '#8b93a3',
        'accent': '#0891b2',
        'accent_hover': '#06b6d4',
        'accent_press': '#0e7490',
        'on_accent': '#ffffff',
        'selection': '#a5e9f5',
        'ok': '#059669',
        'warn': '#b45309',
        'danger': '#dc2626',
        'info': '#4f46e5',
    },
}

# 現在の配色。apply() で中身を入れ替える(参照先は同じ dict のまま)
T: dict[str, str] = dict(PALETTES['dark'])
_mode = 'dark'


class _Notifier(QObject):
    changed = Signal(str)       # 'dark' | 'light'


_notifier: _Notifier | None = None


def notifier() -> _Notifier:
    """配色が変わったことを知らせる。色を直接使う画面(状態の色・アイコン)はこれで描き直す。"""
    global _notifier
    if _notifier is None:
        _notifier = _Notifier()
    return _notifier


def status_color(status: str) -> str:
    return T[{'queued': 'muted', 'scheduled': 'info', 'running': 'accent', 'paused': 'warn',
              'done': 'ok', 'error': 'danger', 'cancelled': 'faint'}.get(status, 'muted')]


def current_mode() -> str:
    return _mode


_SVGS = {
    'arrow.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="6" viewBox="0 0 10 6">'
                 '<path d="M1 1l4 4 4-4" fill="none" stroke="{muted}" stroke-width="1.6" stroke-linecap="round" '
                 'stroke-linejoin="round"/></svg>',
    'check.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                 '<path d="M2.5 6.2l2.3 2.3 4.7-5" fill="none" stroke="{on_accent}" stroke-width="1.9" '
                 'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    'pause.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                 '<path d="M5.5 3.5v9M10.5 3.5v9" stroke="{muted}" stroke-width="2" stroke-linecap="round"/></svg>',
    'play.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                '<path d="M5 3.3v9.4a.5.5 0 0 0 .77.42l7.2-4.7a.5.5 0 0 0 0-.84l-7.2-4.7A.5.5 0 0 0 5 3.3z" fill="{muted}"/></svg>',
    'close.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                 '<path d="M4 4l8 8M12 4l-8 8" stroke="{muted}" stroke-width="1.7" stroke-linecap="round"/></svg>',
    'folder.svg': '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                  '<path d="M2 4.5A1.5 1.5 0 0 1 3.5 3h2.8l1.5 1.5h4.7A1.5 1.5 0 0 1 14 6v5.5a1.5 1.5 0 0 1-1.5 1.5h-9'
                  'A1.5 1.5 0 0 1 2 11.5z" fill="none" stroke="{muted}" stroke-width="1.5" stroke-linejoin="round"/></svg>',
}


@functools.lru_cache(maxsize=None)
def _icon(name: str, mode: str) -> 'QIcon':
    return QIcon(f'{_assets_dir(mode)}/{name}.svg')


def icon(name: str) -> 'QIcon':
    return _icon(name, _mode)


@functools.lru_cache(maxsize=None)
def _assets_dir(mode: str) -> str:
    """QSS の url() はファイルしか参照できないので、SVG を配色ごとにデータフォルダへ書き出す。"""
    from .. import paths
    d = paths.data_dir() / 'ui' / mode
    d.mkdir(parents=True, exist_ok=True)
    for name, svg in _SVGS.items():
        target = d / name
        content = svg.format(**PALETTES[mode])
        try:
            if not target.is_file() or target.read_text(encoding='utf-8') != content:
                target.write_text(content, encoding='utf-8')
        except OSError:
            pass
    return d.as_posix()


# 漢字の字形は先に来たフォントで決まるので、言語ごとに CJK フォントの順を変える
_CJK_FONTS = {
    'ja': '"Yu Gothic UI", "Meiryo UI"',
    'ko': '"Malgun Gothic"',
    'zh_CN': '"Microsoft YaHei UI", "Microsoft YaHei"',
}


def font_families(lang: str) -> str:
    return '"Segoe UI", ' + _CJK_FONTS.get(lang, _CJK_FONTS['ja']) + ', sans-serif'


def qss(lang: str = 'ja') -> str:
    c = T
    a = _assets_dir(_mode)
    return f"""
* {{ font-family: {font_families(lang)}; font-size: 10pt; color: {c['text']}; }}
QMainWindow, QWidget#root {{ background: {c['bg']}; }}
QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['bg']}; border: none; }}
QWidget#sidebar {{ background: {c['side']}; border-right: 1px solid {c['border']}; }}
QLabel#brand {{ font-size: 17pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#brandSub {{ color: {c['muted']}; font-size: 8.5pt; }}
QLabel#h1 {{ font-size: 16pt; font-weight: 700; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted, QLabel[muted="true"] {{ color: {c['muted']}; }}
QLabel#faint {{ color: {c['faint']}; font-size: 9pt; }}
QLabel#title {{ font-size: 12.5pt; font-weight: 600; }}
QLabel#chip {{ background: {c['surface3']}; color: {c['muted']}; border-radius: 9px; padding: 2px 9px; font-size: 8.5pt; }}
QLabel#warnText {{ color: {c['warn']}; font-size: 9pt; }}
QLabel#errText {{ color: {c['danger']}; }}
QLabel#okText {{ color: {c['ok']}; }}
QLabel#thumb {{ background: {c['surface3']}; border-radius: 8px; }}
QPushButton#updLink {{ background: transparent; border: none; color: {c['warn']}; text-align: left; padding: 5px 0; }}
QPushButton#updLink:hover {{ text-decoration: underline; }}
QStatusBar {{ color: {c['muted']}; background: {c['bg']}; }}

QPushButton#nav {{ text-align: left; padding: 10px 14px; border: none; border-radius: 8px; background: transparent;
    color: {c['muted']}; font-size: 10.5pt; }}
QPushButton#nav:hover {{ background: {c['surface']}; color: {c['text']}; }}
QPushButton#nav:checked {{ background: {c['surface2']}; color: {c['accent']}; font-weight: 600; }}

QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#jobCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#jobCard[selected="true"] {{ border: 1px solid {c['accent']}; }}
QFrame#urlBar {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#urlBar[focus="true"] {{ border: 1px solid {c['accent']}; }}
QFrame#sep {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}

QLineEdit, QSpinBox, QDateTimeEdit, QComboBox, QPlainTextEdit {{
    background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 6px 9px;
    selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
QLineEdit:focus, QSpinBox:focus, QDateTimeEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled, QDateTimeEdit:disabled, QComboBox:disabled {{ color: {c['faint']}; background: {c['surface']}; }}
QLineEdit#url {{ background: transparent; border: none; font-size: 12pt; padding: 8px 4px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow, QDateTimeEdit::down-arrow {{ image: url("{a}/arrow.svg"); width: 10px; height: 6px; margin-right: 8px; }}
QDateTimeEdit::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {c['surface2']}; border: 1px solid {c['border']}; outline: none;
    selection-background-color: {c['surface3']}; selection-color: {c['accent']}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDateTimeEdit::up-button, QDateTimeEdit::down-button {{ width: 0; border: none; }}
QPlainTextEdit#log {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 9pt; color: {c['muted']};
    background: {c['side']}; }}

QPushButton {{ background: {c['surface3']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {c['muted']}; }}
QPushButton:pressed {{ background: {c['surface2']}; }}
QPushButton:disabled {{ color: {c['faint']}; border-color: {c['surface3']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['on_accent']}; border: none; font-weight: 700; padding: 9px 20px; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
QPushButton#primary:pressed {{ background: {c['accent_press']}; }}
QPushButton#primary:disabled {{ background: {c['surface3']}; color: {c['faint']}; }}
QPushButton#ghost {{ background: transparent; border: none; color: {c['muted']}; padding: 5px 8px; }}
QPushButton#ghost:hover {{ color: {c['text']}; background: {c['surface2']}; }}
QPushButton#icon {{ background: transparent; border: none; border-radius: 6px; padding: 4px; min-width: 26px; min-height: 26px;
    color: {c['muted']}; font-size: 11pt; }}
QPushButton#icon:hover {{ background: {c['surface3']}; color: {c['text']}; }}
QPushButton#danger {{ background: transparent; border: 1px solid {c['border']}; color: {c['danger']}; }}
QPushButton#danger:hover {{ border-color: {c['danger']}; }}
QPushButton#seg {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 0; padding: 7px 18px; color: {c['muted']}; }}
QPushButton#seg:checked {{ background: {c['surface3']}; color: {c['accent']}; font-weight: 600; border-color: {c['accent']}; }}
QPushButton#segL {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QPushButton#segR {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {c['faint']}; background: {c['surface2']}; }}
QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; image: url("{a}/check.svg"); }}
QCheckBox::indicator:disabled {{ border-color: {c['surface3']}; background: {c['surface']}; }}
QCheckBox::indicator:checked:disabled {{ background: {c['faint']}; border-color: {c['faint']}; }}
QCheckBox:disabled {{ color: {c['faint']}; }}

QProgressBar {{ background: {c['surface3']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QProgressBar[state="done"]::chunk {{ background: {c['ok']}; }}
QProgressBar[state="error"]::chunk {{ background: {c['danger']}; }}
QProgressBar[state="paused"]::chunk {{ background: {c['warn']}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['surface3']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['surface3']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0; background: none; }}

QTableView {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; gridline-color: transparent;
    selection-background-color: {c['surface3']}; selection-color: {c['text']}; alternate-background-color: {c['surface2']}; }}
QTableView::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{ background: {c['surface']}; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']};
    padding: 7px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['surface']}; border: none; }}
QToolTip {{ background: {c['surface3']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 5px; }}
QMenu {{ background: {c['surface2']}; border: 1px solid {c['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['surface3']}; color: {c['accent']}; }}
QDialog {{ background: {c['bg']}; }}
QMessageBox {{ background: {c['surface']}; }}
QCalendarWidget QWidget {{ alternate-background-color: {c['surface2']}; }}
"""


def resolve_mode(setting: str) -> str:
    """'system' を実際の 'dark' / 'light' へ。OS の配色が取れなければダーク。"""
    if setting in ('dark', 'light'):
        return setting
    from PySide6.QtGui import QGuiApplication
    hints = QGuiApplication.styleHints()
    hints.unsetColorScheme()    # 以前に明示した配色を解除してから OS の値を読む
    return 'light' if hints.colorScheme() == Qt.ColorScheme.Light else 'dark'


_applying = False


def apply(setting: str, lang: str = 'ja') -> str:
    """配色を切り替えてアプリ全体へ適用する。適用した 'dark' / 'light' を返す。

    明示(dark/light)のときは Qt にも配色を指定し、タイトルバー等のネイティブ部分を揃える(Qt 6.8+)。
    'system' のときは指定を解除したままにする。指定すると OS の切り替えを追えなくなるため。
    """
    global _mode, _applying
    from PySide6.QtWidgets import QApplication
    _applying = True
    try:
        _mode = resolve_mode(setting)
        T.clear()
        T.update(PALETTES[_mode])
        app = QApplication.instance()
        if app is not None:
            if setting in ('dark', 'light'):
                app.styleHints().setColorScheme(Qt.ColorScheme.Dark if _mode == 'dark' else Qt.ColorScheme.Light)
            app.setStyleSheet(qss(lang))
            notifier().changed.emit(_mode)
    finally:
        _applying = False
    return _mode


def follow_system(setting: str, lang: str) -> None:
    """OS の配色が変わったとき。「システムに合わせる」で、実際に変わった場合だけ適用し直す。"""
    if _applying or setting != 'system':
        return
    if resolve_mode('system') != _mode:
        apply('system', lang)


def app_icon() -> QIcon:
    """外部画像を持たずに描くアプリアイコン(角丸の四角+下向き矢印)。配色に依らず常にダーク版。"""
    P = PALETTES['dark']
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = float(size)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P['surface2']))
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.24, s * 0.24)
        pen = QPen(QColor(P['accent']), max(1.5, s * 0.1), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(s * .5, s * .22), QPointF(s * .5, s * .62))
        path = QPainterPath(QPointF(s * .31, s * .46))
        path.lineTo(QPointF(s * .5, s * .64))
        path.lineTo(QPointF(s * .69, s * .46))
        p.drawPath(path)
        p.drawLine(QPointF(s * .28, s * .78), QPointF(s * .72, s * .78))
        p.end()
        icon.addPixmap(pm)
    return icon
