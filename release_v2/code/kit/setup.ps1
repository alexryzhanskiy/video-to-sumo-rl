# One-time set-up of the E12 kit on a Windows PC (about 3-5 min): a Python 3.13 environment in .venv with the
# pinned packages (SUMO 1.26.0 + libsumo, torch CPU, pfrl, gym 0.22.0), then the identity checks and the
# throughput test. Needs uv (README.md, step 1); uv downloads Python 3.13 itself.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'uv is not installed. Install it (README.md, step 1), open a new PowerShell window and run this again.'
    exit 1
}
if (-not (Test-Path .venv\Scripts\python.exe)) {
    uv venv .venv --python 3.13
    if ($LASTEXITCODE -ne 0) { exit 1 }
}
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit 1 }
.venv\Scripts\python.exe e12.py verify
if ($LASTEXITCODE -ne 0) {
    Write-Host 'verify FAILED: do not start E12; report runs\verify.json'
    exit 1
}
.venv\Scripts\python.exe e12.py bench
