@echo off
set CURRENT_DIR=%CD%
echo ***** Current directory: %CURRENT_DIR% *****
set PYTHONPATH=%CURRENT_DIR%;%PYTHONPATH%

rem If you could not download the model from the official site, you can use the mirror site.
rem Just remove the comment of the following line (remove rem).
rem 如果你无法从官方网站下载模型，你可以使用镜像网站。
rem 只需要移除下面一行的注释即可（移除 rem）。

rem set HF_ENDPOINT=https://hf-mirror.com

streamlit run .\webui\Main.py