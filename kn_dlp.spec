# PyInstaller spec — `pyinstaller kn_dlp.spec` (scripts/build.ps1 経由で実行)
# 構成: onedir に GUI(kn_dlp.exe, windowed) とワーカー(kn_dlp_worker.exe, console) を同居させる。
# yt-dlp 本体は同梱の vendor/yt-dlp.pyz から読む(更新で差し替え可能にするため PYZ には入れない)。
import importlib.util
import sys

from PyInstaller.utils.hooks import collect_submodules

# yt-dlp の将来版が新たに使う標準ライブラリにも備え、プラットフォームで import 可能な stdlib を広く同梱する
_SKIP_STDLIB = {'tkinter', '_tkinter', 'turtle', 'turtledemo', 'idlelib', 'test', 'lib2to3', 'ensurepip', 'venv',
                'pydoc_data', 'distutils', 'msilib', 'antigravity', 'this', 'curses', '_curses', 'readline',
                '_pyrepl', 'pydoc', 'doctest', 'unittest', 'tomllib'}
_top = sorted(m for m in sys.stdlib_module_names
              if m not in _SKIP_STDLIB and not m.startswith('_') and importlib.util.find_spec(m) is not None)


def _no_tests(name: str) -> bool:
    parts = name.split('.')
    return not any(p in ('test', 'tests', 'idle_test', 'SelfTest', '__main__') for p in parts)


# 名前だけ指定するとパッケージの __init__ しか入らない(xml.etree 等が欠ける)ため、サブモジュールごと集める
stdlib = []
for m in _top:
    spec = importlib.util.find_spec(m)
    stdlib += collect_submodules(m, filter=_no_tests) if spec.submodule_search_locations else [m]

# yt-dlp の任意依存(あれば機能が増える)。サブモジュールごと同梱する
ytdlp_deps = []
# mutagen (GPL-2.0+) は本体が GPL-3.0 なので同梱できる。Opus/FLAC へのサムネ埋め込みに使う
for pkg in ('certifi', 'brotli', 'websockets', 'requests', 'urllib3', 'Cryptodome', 'curl_cffi', 'mutagen'):
    if importlib.util.find_spec(pkg) is not None:
        ytdlp_deps += collect_submodules(pkg, filter=_no_tests) if pkg != 'brotli' else ['brotli']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('vendor/yt-dlp.pyz', 'vendor'), ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.')],
    hiddenimports=stdlib + ytdlp_deps + ['PySide6.QtSvg', 'kn_dlp.worker', 'kn_dlp.ui.app'],
    excludes=['yt_dlp', 'yt_dlp_ejs', 'tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.Qt3DCore', 'PySide6.QtMultimedia', 'PySide6.QtPdf', 'PySide6.QtCharts',
              'PySide6.QtDataVisualization', 'PySide6.QtBluetooth', 'PySide6.QtPositioning', 'PySide6.QtSql'],
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(debug=False, bootloader_ignore_signals=False, strip=False, upx=False, icon='assets/kn_dlp.ico',
              version=None)
# 開発時(PYTHONUTF8=1)と同じく UTF-8 モードで動かす
utf8 = [('X utf8', None, 'OPTION')]
gui = EXE(pyz, a.scripts, utf8, exclude_binaries=True, name='kn_dlp', console=False, **common)
worker = EXE(pyz, a.scripts, utf8, exclude_binaries=True, name='kn_dlp_worker', console=True, **common)
coll = COLLECT(gui, worker, a.binaries, a.datas, strip=False, upx=False, name='kn_dlp')
