@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "FRONTEND_DIR=%ROOT_DIR%frontend"
set "PYTHON_EXE=%ROOT_DIR%.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

echo ***** Starting MoneyPrinterTurbo API on http://127.0.0.1:8080 *****
start "MoneyPrinterTurbo API" /min cmd /c "cd /d "%ROOT_DIR%" && "%PYTHON_EXE%" main.py"

echo ***** Starting Next.js UI on http://127.0.0.1:3000 *****
cd /d "%FRONTEND_DIR%"
call npm run dev
