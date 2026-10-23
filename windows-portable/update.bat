@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup-And-Start.ps1" -UpdateOnly
set "RESULT=%ERRORLEVEL%"
if "%RESULT%"=="0" (echo Update completed.) else (echo Update stopped with error %RESULT%. See the message above.)
pause
exit /b %RESULT%
