"""GUI の起動。"""
from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, Qt, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .. import APP_DISPLAY_NAME, APP_NAME, i18n


def _install_qt_translator(app: QApplication, lang: str) -> None:
    """QMessageBox の「はい/いいえ」など Qt 標準の文言を翻訳する。見つからなければ英語のまま。"""
    if lang == 'en':
        return
    tr = QTranslator(app)
    if tr.load(f'qtbase_{lang}', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(tr)


def main() -> int:
    if sys.platform.startswith('win'):
        try:  # タスクバーで python.exe ではなく本アプリのアイコンを出す
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f'kn.{APP_NAME}')
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setStyle('Fusion')

    from ..settings import Settings
    settings = Settings()
    lang = i18n.set_language(settings['language'])   # 画面を作る前に決める(切り替えは再起動で反映)
    _install_qt_translator(app, lang)
    from . import theme
    app.setFont(QFont(theme.font_families(lang).split(',')[0].strip('" '), 10))
    theme.apply(settings['theme'], lang)
    # 「システムに合わせる」のときは OS 側の切り替えに追従する
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: theme.follow_system(settings['theme'], lang))
    app.setWindowIcon(theme.app_icon())

    from .main_window import MainWindow
    win = MainWindow(settings)
    win.show()
    return app.exec()
