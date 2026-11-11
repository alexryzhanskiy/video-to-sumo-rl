# Starts E13 (run_e13.ps1) in its own PowerShell window and returns at once, so the run does not depend on the
# terminal or the Claude Code session that started it. Progress: ..\.venv\Scripts\python.exe e13.py status
# -Locked runs the locked test instead (once, only when Pavlo asks for it).
param([int]$Workers = 0, [switch]$Locked)
Set-Location $PSScriptRoot
$py = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { Write-Host 'No .venv yet: run ..\setup.ps1 first (E12 set-up).'; exit 1 }
& $py e13.py running
if ($LASTEXITCODE -eq 0) { Write-Host 'E13 is already running.'; & $py e13.py status; exit 0 }
$argList = @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'run_e13.ps1'))
if ($Workers -gt 0) { $argList += @('-Workers', $Workers) }
if ($Locked) { $argList += '-Locked' }
Start-Process powershell -ArgumentList $argList -WorkingDirectory $PSScriptRoot
Start-Sleep -Seconds 20
& $py e13.py status
