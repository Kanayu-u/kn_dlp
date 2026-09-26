Set-Location $PSScriptRoot\..
.\.venv\Scripts\python -m pip install -q "yt-dlp[default,curl-cffi]" pyinstaller 2>&1 | Select-Object -Last 5
.\.venv\Scripts\python -m pip list 2>$null | Select-String 'curl|brotli|certifi|websockets|requests|urllib3|mutagen|pycryptodomex|pyinstaller|PySide6|yt-dlp'
