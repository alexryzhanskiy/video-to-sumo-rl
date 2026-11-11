# Runs everything: verify, train, eval, pack, publish (results/ pushed, zip uploaded). Safe to run again after a
# stop: finished parts are skipped. Optional: -Workers N (default: the value suggested by setup.ps1's test).
# start_e12.ps1 opens this in its own window.
param([int]$Workers = 0)
Set-Location $PSScriptRoot
$Host.UI.RawUI.WindowTitle = 'E12 run - keep this window open'
$py = '.venv\Scripts\python.exe'
if ($Workers -gt 0) { & $py e12.py all --publish --workers $Workers } else { & $py e12.py all --publish }
