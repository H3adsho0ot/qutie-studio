param([string]$ListenAddress = '127.0.0.1', [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ and try again.' }
    & '.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Installation failed.' }
}
Write-Host "Qutie Studio: http://localhost:$Port"
& '.venv\Scripts\python.exe' -m uvicorn app:app --host $ListenAddress --port $Port --workers 1
