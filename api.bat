@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py
    exit /b %errorlevel%
)

where uv >nul 2>nul
if not errorlevel 1 (
    uv run python main.py
    exit /b %errorlevel%
)

echo ***** No Python environment found. Run install.bat first *****
echo ***** or run webui.bat for automatic first-time setup. *****
pause
exit /b 1
