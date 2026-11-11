# Runs E13: verify, baselines, L0, B1 replay, L1+L2, selection, L3+L4, final selection, pack, publish (results
# pushed after L1+L2 and at the end). Safe to run again after a stop: finished parts are skipped.
# -Locked: the locked test (once; only when Pavlo asks), then pack and publish. -Workers N: parallel processes.
# start_e13.ps1 opens this in its own window.
param([int]$Workers = 0, [switch]$Locked)
Set-Location $PSScriptRoot
$py = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'
$w = @()
if ($Workers -gt 0) { $w = @('--workers', $Workers) }
if ($Locked) {
    $Host.UI.RawUI.WindowTitle = 'E13 LOCKED TEST - keep this window open'
    & $py e13.py locked --go @w
    & $py e13.py pack
    & $py e13.py publish
} else {
    $Host.UI.RawUI.WindowTitle = 'E13 run - keep this window open'
    & $py e13.py all --publish @w
}
