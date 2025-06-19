@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****
set PYTHONPATH=%CURRENT_DIR%

rem Activate Python virtual environment if exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

rem Optional Hugging Face mirror setting
rem set HF_ENDOINT=https://hf-mirror.com

streamlit run .\webui\Main.py --browser.gatherUsageStats=False --server.enableCORS=True