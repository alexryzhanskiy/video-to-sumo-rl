@echo off
REM Activate RESCO virtual environment
echo Activating RESCO virtual environment...
call .\resco_env\Scripts\activate.bat
echo Virtual environment activated!
echo.
echo To run the benchmark, use:
echo python -m resco_benchmark.main --help
echo.
cmd /k