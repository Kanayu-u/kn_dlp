# Third-party notices

KN DLP 本体は GPL-3.0 です(`LICENSE`)。配布物(dist/kn_dlp)には以下のソフトウェアが含まれます。

| ソフトウェア | ライセンス | 入手先 |
|---|---|---|
| yt-dlp (vendor/yt-dlp.pyz, yt-dlp-ejs を内包) | Unlicense | https://github.com/yt-dlp/yt-dlp |
| Python | PSF License | https://www.python.org/ |
| Qt 6 / PySide6 | LGPL-3.0 | https://www.qt.io/ , https://code.qt.io/ |
| certifi | MPL-2.0 | https://github.com/certifi/python-certifi |
| requests | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | MIT | https://github.com/urllib3/urllib3 |
| websockets | BSD-3-Clause | https://github.com/python-websockets/websockets |
| Brotli | MIT | https://github.com/google/brotli |
| pycryptodomex | BSD-2-Clause / Public Domain | https://github.com/Legrandin/pycryptodome |
| curl_cffi (curl-impersonate を内包) | MIT | https://github.com/lexiforest/curl_cffi |
| mutagen | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |

## Qt / PySide6 (LGPL-3.0)
Qt と PySide6 は動的ライブラリ(`_internal/PySide6/` 配下の DLL / pyd)として同梱しており、
利用者はこれらを互換のある別ビルドへ差し替えられます。ソースコードは上記の入手先から取得できます。

## Qt の翻訳ファイル
Qt 標準ダイアログの翻訳(`qtbase_*.qm`)は Qt に含まれるもので、Qt と同じ LGPL-3.0 です。

## 同梱しないもの
- **ffmpeg**: 本アプリには含みません。設定画面の「ffmpeg を自動取得」は、利用者の操作により
  yt-dlp 公式の FFmpeg-Builds (GPL) を利用者の PC に直接ダウンロードします。
