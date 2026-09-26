# KN DLP

**日本語** | [English](README.en.md)

[yt-dlp](https://github.com/yt-dlp/yt-dlp) の Windows 向けデスクトップ GUI です。
バージョン: **0.2.0** / ライセンス: **GPL-3.0**

## 主な機能

| 機能 | 内容 |
|---|---|
| URL 解析 | サムネイル・タイトル・長さ・字幕の言語・チャプター数・形式数を表示します。URL は貼り付けのほか、ウィンドウへのドロップでも入力できます |
| 形式 | 動画は画質(最高〜360p)とコンテナ(自動/MP4/MKV/WebM)、音声は MP3/M4A/Opus/FLAC/WAV を選べます。形式一覧から映像と音声を個別に選んで結合することもできます |
| キュー | 同時実行数を 1〜8 で設定できます。一時停止すると途中から再開でき、キャンセルすると途中ファイルを削除します。進捗・速度・残り時間を表示します |
| 範囲切り出し | 開始・終了の時刻を指定して、その区間だけを取得します。「正確に切る」を選ぶと再エンコードします |
| 字幕・チャプター・サムネ | 字幕の言語指定、自動生成字幕、動画への埋め込み、チャプター・サムネイル・メタデータの埋め込みができます |
| 履歴 | SQLite に記録し、検索・再生・フォルダを開く・同じ設定での再ダウンロードができます |
| yt-dlp 更新 | 公式の最新リリースを取得し、SHA-256 を検証してから差し替えます。1つ前の版に戻すことも、同梱版に戻すこともできます。アプリの再起動は不要です |
| プロファイル | 設定の組み合わせを名前を付けて保存できます。組み込みで4種類あります |
| ライブ・予約 | 配信の開始を待って録画できます。開始時刻を指定した予約もできます |
| Cookie | ブラウザの Cookie、または cookies.txt を使えます。Cookie はアプリに保存しません |
| エラー表示 | よくある失敗を要約し、対処も表示します(原文はログに残ります) |
| 多言語 | 日本語・英語・韓国語・中国語(簡体)。既定は OS の言語で、設定画面から変更できます(再起動で反映) |
| テーマ | システムに合わせる / ダーク / ライト。切り替えはその場で反映されます |
| プラグイン | yt-dlp 公式のプラグインで、サイト対応や後処理を追加できます。設定画面で読み込んだプラグインと読み込みエラーを確認できます |

## 動作環境

- Windows 10 / 11 (x64)
- **ffmpeg**: 結合・音声変換・切り出し・埋め込みに必要です。設定画面の「ffmpeg を自動取得」で、yt-dlp 公式ビルドを取得できます
- **JS ランタイム** (deno / Node.js / Bun のどれか): YouTube の署名解読に必要です。自動で検出します

## 使い方(配布版)

1. [Releases](../../releases) から `kn_dlp-<版>-win64.zip` を取得・展開し、`kn_dlp.exe` を起動します
2. 初回は「設定」で ffmpeg と JS ランタイムの検出状況を確認します
3. 「新規ダウンロード」で URL を入力し、解析してからキューに追加します

データ(設定・履歴・更新版の yt-dlp・ffmpeg)は `%LOCALAPPDATA%\kn_dlp` に保存されます。

### プラグイン

[yt-dlp のプラグイン](https://github.com/yt-dlp/yt-dlp#plugins)を次の場所に置くと、次のダウンロードから使われます。

```
%LOCALAPPDATA%\kn_dlp\plugins\<名前>\yt_dlp_plugins\extractor\<名前>.py      (サイト対応)
%LOCALAPPDATA%\kn_dlp\plugins\<名前>\yt_dlp_plugins\postprocessor\<名前>.py  (後処理)
```

設定画面の「プラグインを追加…」か、`.py` / `.zip` をウィンドウへドロップすると、この形に置きます(GitHub の「Download ZIP」は `yt_dlp_plugins` だけを取り出します)。「雛形を作る」でサイト対応・後処理の雛形を作れ、「URL の判定」で、その URL にどの対応(プラグイン / yt-dlp 標準 / 汎用)が使われるかを確かめられます。設定画面の「読み込む場所」で、kn_dlp 専用フォルダに加えて yt-dlp 本体の既定の場所(`%APPDATA%\yt-dlp\plugins` など)も読むか(すべて)、専用フォルダだけか、読み込まないかを選べます。
**後処理のプラグインは、読み込んだだけでは動きません**(yt-dlp の `--use-postprocessor` と同じ仕様)。設定画面の一覧で「実行する」にし、実行する時点と引数(`key=value` を `;` で区切る)を指定します。同じ時点の標準の後処理(埋め込みなど)より後に動きます。

プラグインはあなたの権限で動く Python コードです。信頼できるものだけを置いてください。yt-dlp の更新で動かなくなることがあります。

## 開発

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python scripts\fetch_ytdlp.py      # vendor/yt-dlp.pyz を取得
.\scripts\devrun.ps1                               # 起動
.\.venv\Scripts\python -m unittest discover -s tests
.\scripts\build.ps1                                # dist/ に exe と zip を作成
```

### 翻訳

UI の文字列は日本語の原文をそのままキーにして `tr('原文')` で引きます(gettext と同じ方式)。
言語を増やすには `kn_dlp/i18n/<コード>.py` に辞書 `T` を作り、`kn_dlp/i18n/__init__.py` の `LANG_NAMES` と `_load`、
`kn_dlp/settings.py` の `LANGUAGES` に登録します。訳の漏れ・余り・置換欄の食い違いは `tests/test_i18n.py` が検出します。

### 構成

```
main.py                 エントリ (--worker で yt-dlp 実行用の子プロセスになる)
kn_dlp/
  bootstrap.py          同梱版/更新版の yt-dlp.pyz のうち新しい方を読み込む
  options.py            ジョブ指定 → YoutubeDL オプション(Qt 非依存・テスト対象)
  worker.py             子プロセス。GUI とは JSON Lines でやり取りする
  updater.py            yt-dlp / ffmpeg の取得(SHA-256 検証・URL 許可リスト)
  plugins.py            yt-dlp プラグインの読み込み範囲と一覧
  history.py settings.py errors.py tools.py timeparse.py paths.py
  i18n/                 翻訳辞書(日本語の原文がキー。en / ko / zh_CN)
  ui/                   PySide6 の画面(queue.py がキュー制御、theme.py が配色)
```

- yt-dlp は **ダウンロード1件ごとに別プロセス** で動かします。キャンセル時は ffmpeg を含めてプロセスツリーごと止めます。また、更新した yt-dlp は次のジョブから使われます
- 配布版では yt-dlp を exe に焼き込まず、`_internal/vendor/yt-dlp.pyz`(公式 zipapp)として置きます。更新はこれより新しい版をデータフォルダに置くことで行います

## 既知の制限

- キューはアプリ終了時に保存されません(完了分は履歴に残ります)
- Chrome / Edge 系の Cookie は、新しい暗号化方式や起動中のファイルロックのため読めないことがあります。Firefox か cookies.txt を推奨します
- WebM・WAV はサムネイルを埋め込めない形式のため、画像ファイルとして横に保存します
- 英語・韓国語・中国語の訳はネイティブ話者の確認を経ていません。改善の提案を歓迎します
- exe には署名していないため、SmartScreen やウイルス対策ソフトが警告を出すことがあります

## ライセンス・免責

本体は GNU General Public License v3.0 です(`LICENSE`)。同梱物のライセンスは `THIRD_PARTY_NOTICES.md` を参照してください。
ダウンロードする内容の権利と、各サイトの利用規約は、利用者ご自身で確認してください。
