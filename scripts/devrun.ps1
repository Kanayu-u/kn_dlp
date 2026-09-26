# 開発用: Windows の venv で main.py を実行する。引数はそのまま渡す。
param([Parameter(ValueFromRemainingArguments=$true)]$Rest)
Set-Location $PSScriptRoot\..
& .\.venv\Scripts\python.exe main.py @Rest
