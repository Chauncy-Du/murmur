@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo MurMur environment is missing. Run: uv sync --locked
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "run.py" %*
set "murmur_exit_code=%errorlevel%"
if not "%murmur_exit_code%"=="0" (
    echo MurMur could not start. Check data\startup-error.log.
    pause
)
exit /b %murmur_exit_code%
