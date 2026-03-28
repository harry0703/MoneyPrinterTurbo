@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****

echo Running Streamlit app directly (command line mode)...


set PYTHONPATH=%CURRENT_DIR%

rem Activate conda environment
call conda activate condaenv-moneyprinter

rem Check if activation was successful
if %ERRORLEVEL% NEQ 0 (
    echo Failed to activate conda environment, please ensure the environment is created
    pause
    exit /b 1
)

rem Run Streamlit app (browser will open automatically by default)
streamlit run .\webui\Main.py --browser.gatherUsageStats=False --server.enableCORS=True --server.maxUploadSize=1024 --server.headless=True

rem Return to original environment
call conda deactivate
