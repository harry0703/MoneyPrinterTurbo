@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-And-Start.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo Setup stopped with error %RESULT%. See the message above.
  pause
)
exit /b %RESULT%
