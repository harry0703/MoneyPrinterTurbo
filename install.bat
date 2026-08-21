@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ***** MoneyPrinterTurbo - one-time setup *****

rem ---------------------------------------------------------------
rem Locate uv, or install it automatically on first run
rem ---------------------------------------------------------------
set "UV_CMD="
where uv >nul 2>nul
if not errorlevel 1 set "UV_CMD=uv"
if not defined UV_CMD if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"

if defined UV_CMD goto :uv_ready

echo ***** uv not found - installing uv automatically, please wait... *****
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
if not errorlevel 1 if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV_CMD=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV_CMD (
    where uv >nul 2>nul
    if not errorlevel 1 set "UV_CMD=uv"
)

if not defined UV_CMD (
    echo ***** Failed to install uv automatically. *****
    echo ***** Please install it manually from https://docs.astral.sh/uv/getting-started/installation/ *****
    echo ***** Then run install.bat again. *****
    pause
    exit /b 1
)

:uv_ready
echo ***** Using uv: %UV_CMD% *****

rem ---------------------------------------------------------------
rem Install Python 3.11 and all dependencies into .venv
rem ---------------------------------------------------------------
"%UV_CMD%" python install 3.11
if errorlevel 1 goto :failed
"%UV_CMD%" sync --frozen
if errorlevel 1 goto :failed

rem ---------------------------------------------------------------
rem Create the local config file on first run
rem ---------------------------------------------------------------
if not exist config.toml (
    echo ***** Creating config.toml from config.example.toml *****
    copy /y config.example.toml config.toml >nul
)

echo.
echo ***** Setup finished successfully! *****
echo ***** Start the WebUI:        run webui.bat *****
echo ***** Start the API service:  run api.bat *****
exit /b 0

:failed
echo ***** Setup failed - see the error messages above. *****
pause
exit /b 1
