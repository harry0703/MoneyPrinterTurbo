@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****
set PYTHONPATH=%CURRENT_DIR%

rem set HF_ENDPOINT=https://hf-mirror.com
streamlit run .\webui\Main.py --browser.gatherUsageStats=False --server.enableCORS=True