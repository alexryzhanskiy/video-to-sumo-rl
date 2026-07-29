# PowerShell script to activate RESCO virtual environment
Write-Host "Activating RESCO virtual environment..." -ForegroundColor Green
& .\resco_env\Scripts\Activate.ps1
Write-Host "Virtual environment activated!" -ForegroundColor Green
Write-Host ""
Write-Host "To run the benchmark, use:" -ForegroundColor Yellow
Write-Host "python -m resco_benchmark.main --help" -ForegroundColor Cyan
Write-Host ""