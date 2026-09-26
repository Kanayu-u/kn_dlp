"""assets/kn_dlp.ico を theme.app_icon() と同じ絵から生成する(ビルド前に 1 回)。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PySide6.QtGui import QGuiApplication  # noqa: E402

app = QGuiApplication(sys.argv)
from kn_dlp.ui.theme import app_icon  # noqa: E402

out = Path(__file__).resolve().parent.parent / 'assets'
out.mkdir(exist_ok=True)
pm = app_icon().pixmap(256, 256)
pm.save(str(out / 'kn_dlp.png'))
ok = pm.save(str(out / 'kn_dlp.ico'))
print('ico', ok)
