"""vendor/yt-dlp.pyz を公式最新リリースに更新する(SHA-256 検証付き)。ビルド前に実行。"""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
os.environ.setdefault('KN_DLP_DATA', str(root / 'build' / 'fetch-data'))
from kn_dlp import bootstrap, updater  # noqa: E402

rel = updater.fetch_latest()
target = root / 'vendor' / 'yt-dlp.pyz'
current = bootstrap.read_pyz_version(target) if target.exists() else None
if current == rel['version']:
    print('vendor/yt-dlp.pyz は最新です', current)
    sys.exit(0)
tmp = target.with_suffix('.download')
target.parent.mkdir(exist_ok=True)
updater._download(rel['asset_url'], tmp, updater.parse_sums(updater._get(rel['sums_url']).decode()), updater.MAX_ASSET_BYTES)
os.replace(tmp, target)
print('vendor/yt-dlp.pyz を更新しました', current, '->', bootstrap.read_pyz_version(target))
