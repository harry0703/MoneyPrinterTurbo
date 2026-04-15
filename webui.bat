@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****

echo Starting MoneyPrinterTurbo with Vue frontend...

set PYTHONPATH=%CURRENT_DIR%

rem Activate conda environment
call conda activate condaenv-moneyprinter

rem Check if activation was successful
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate conda environment, please ensure the environment is created
    pause
    exit /b 1
)

rem Start backend API in a new window
start "Backend API" cmd /c "cd /d %CURRENT_DIR% && python main.py"

rem Wait for backend to start
ping localhost -n 5 > nul

echo Backend API started. Starting Vue frontend...

rem Check if Vue frontend is built
if exist "%CURRENT_DIR%\vue-frontend\dist" (
    echo Serving production build...
    rem Use Python's built-in server for production build
    start "Vue Frontend" cmd /c "cd /d %CURRENT_DIR%\vue-frontend\dist && python -m http.server 3000"
) else (
    echo Starting development server...
    rem Start Vue development server
    start "Vue Frontend" cmd /c "cd /d %CURRENT_DIR%\vue-frontend && npm run dev"
)

echo Frontend started. Opening browser...

rem Open browser to Vue frontend
start http://localhost:3000

echo MoneyPrinterTurbo is running!
echo Backend API: http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Press any key to stop the application...
pause

echo Stopping application...

rem Kill the backend and frontend processes
for /f "tokens=2" %%i in ('tasklist ^| findstr "python.exe" ^| findstr "main.py"') do taskkill /F /PID %%i
for /f "tokens=2" %%i in ('tasklist ^| findstr "node.exe" ^| findstr "vite"') do taskkill /F /PID %%i
for /f "tokens=2" %%i in ('tasklist ^| findstr "python.exe" ^| findstr "http.server"') do taskkill /F /PID %%i

rem Return to original environment
call conda deactivate

echo Application stopped.
