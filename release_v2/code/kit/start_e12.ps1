# Starts E12 (run_e12.ps1) in its own PowerShell window and returns at once, so the run does not depend on the
# terminal or the Claude Code session that started it. Progress: .venv\Scripts\python.exe e12.py status
param([int]$Workers = 0)
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Host 'No .venv yet: run setup.ps1 first.'; exit 1 }
& $py e12.py running
if ($LASTEXITCODE -eq 0) { Write-Host 'E12 is already running.'; & $py e12.py status; exit 0 }
$argList = @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'run_e12.ps1'))
if ($Workers -gt 0) { $argList += @('-Workers', $Workers) }
Start-Process powershell -ArgumentList $argList -WorkingDirectory $PSScriptRoot
Start-Sleep -Seconds 20
& $py e12.py status
