# リリースビルド: yt-dlp 取得 → テスト → アイコン → PyInstaller → zip
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot\..
$py = '.\.venv\Scripts\python.exe'
& $py scripts\fetch_ytdlp.py
& $py -m unittest discover -s tests
if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
if (-not (Test-Path assets\kn_dlp.ico)) { & $py scripts\make_icon.py }
& $py -m PyInstaller --noconfirm --clean kn_dlp.spec
if ($LASTEXITCODE -ne 0) { throw 'pyinstaller failed' }
$ver = (& $py -c "import kn_dlp; print(kn_dlp.__version__)").Trim()
$zip = "dist\kn_dlp-$ver-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\kn_dlp -DestinationPath $zip
# build\ は PyInstaller の作業用(中の exe は単体では起動できない)なので残さない
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Write-Host "OK: $zip"
