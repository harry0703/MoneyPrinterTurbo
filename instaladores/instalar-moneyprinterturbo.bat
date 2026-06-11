@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Instalador MoneyPrinterTurbo

echo ==========================================================
echo    INSTALADOR DO MONEYPRINTERTURBO (Windows)
echo    Gerador de videos curtos com IA - 100%% no seu PC
echo ==========================================================
echo.

set "INSTALL_DIR=%USERPROFILE%\MoneyPrinterTurbo"

rem ---------- Verifica o winget ----------
where winget >nul 2>nul
if errorlevel 1 (
    echo [ERRO] O 'winget' nao foi encontrado.
    echo Instale o "Instalador de Aplicativo" pela Microsoft Store e rode este instalador de novo.
    pause
    exit /b 1
)

rem ---------- Fase 1: pre-requisitos ----------
set "NEED_RESTART=0"

where git >nul 2>nul
if errorlevel 1 (
    echo [1/4] Instalando Git...
    winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements
    set "NEED_RESTART=1"
) else (
    echo [1/4] Git ja instalado. OK
)

py -3.12 -c "pass" >nul 2>nul
if errorlevel 1 (
    py -3.11 -c "pass" >nul 2>nul
    if errorlevel 1 (
        echo [2/4] Instalando Python 3.12...
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
        set "NEED_RESTART=1"
    ) else (
        echo [2/4] Python 3.11 ja instalado. OK
    )
) else (
    echo [2/4] Python 3.12 ja instalado. OK
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [3/4] Instalando FFmpeg...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    set "NEED_RESTART=1"
) else (
    echo [3/4] FFmpeg ja instalado. OK
)

where magick >nul 2>nul
if errorlevel 1 (
    echo [4/4] Instalando ImageMagick...
    winget install --id ImageMagick.ImageMagick -e --accept-source-agreements --accept-package-agreements
    set "NEED_RESTART=1"
) else (
    echo [4/4] ImageMagick ja instalado. OK
)

if "%NEED_RESTART%"=="1" (
    echo.
    echo ==========================================================
    echo  Programas base instalados com sucesso!
    echo.
    echo  IMPORTANTE: feche esta janela e execute o instalador
    echo  NOVAMENTE para concluir. ^(O Windows precisa reabrir o
    echo  terminal para reconhecer os novos programas.^)
    echo ==========================================================
    pause
    exit /b 0
)

rem ---------- Fase 2: baixar o programa ----------
echo.
if exist "%INSTALL_DIR%\webui\Main.py" (
    echo Programa ja baixado em %INSTALL_DIR%. Atualizando...
    cd /d "%INSTALL_DIR%"
    git pull
) else (
    echo Baixando o MoneyPrinterTurbo para %INSTALL_DIR% ...
    git clone https://github.com/ThalesAndrades/MoneyPrinterTurbo.git "%INSTALL_DIR%"
    if errorlevel 1 (
        echo [ERRO] Falha ao baixar o programa. Verifique sua internet.
        pause
        exit /b 1
    )
    cd /d "%INSTALL_DIR%"
)

rem ---------- Fase 3: ambiente Python ----------
set "PYCMD="
py -3.12 -c "pass" >nul 2>nul && set "PYCMD=py -3.12"
if not defined PYCMD py -3.11 -c "pass" >nul 2>nul && set "PYCMD=py -3.11"
if not defined PYCMD (
    echo [ERRO] Python 3.11/3.12 nao encontrado. Rode o instalador de novo.
    pause
    exit /b 1
)

if not exist "%INSTALL_DIR%\.venv\Scripts\python.exe" (
    echo Criando ambiente Python isolado ^(.venv^)...
    %PYCMD% -m venv "%INSTALL_DIR%\.venv"
)

echo Instalando as dependencias ^(pode levar varios minutos^)...
"%INSTALL_DIR%\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
"%INSTALL_DIR%\.venv\Scripts\python.exe" -m pip install -r "%INSTALL_DIR%\requirements.txt"
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias. Veja as mensagens acima.
    pause
    exit /b 1
)

rem ---------- Fase 4: configuracao ----------
if not exist "%INSTALL_DIR%\config.toml" (
    copy "%INSTALL_DIR%\config.example.toml" "%INSTALL_DIR%\config.toml" >nul
    echo.
    echo ==========================================================
    echo  CONFIGURACAO DAS CHAVES ^(gratuitas^)
    echo ==========================================================
    echo.
    echo  1^) Chave do PEXELS ^(videos de fundo, gratuita^):
    echo     Crie em: https://www.pexels.com/api/
    echo.
    set /p PEXELS_KEY="Cole sua chave do Pexels e tecle Enter: "
    if defined PEXELS_KEY (
        powershell -NoProfile -Command "(Get-Content '%INSTALL_DIR%\config.toml') -replace 'pexels_api_keys = \[\]', 'pexels_api_keys = [\"!PEXELS_KEY!\"]' | Set-Content '%INSTALL_DIR%\config.toml'"
    )
    echo.
    echo  2^) Chave do LLM ^(escreve os roteiros^):
    echo     - Se tiver chave da OpenAI, cole abaixo.
    echo     - Se NAO tiver, so tecle Enter: sera usado o
    echo       Pollinations ^(gratuito, sem chave^).
    echo.
    set /p LLM_KEY="Cole sua chave OpenAI (ou Enter para gratuito): "
    if defined LLM_KEY (
        powershell -NoProfile -Command "(Get-Content '%INSTALL_DIR%\config.toml') -replace 'openai_api_key = \"\"', 'openai_api_key = \"!LLM_KEY!\"' | Set-Content '%INSTALL_DIR%\config.toml'"
    ) else (
        powershell -NoProfile -Command "(Get-Content '%INSTALL_DIR%\config.toml') -replace 'llm_provider = \"openai\"', 'llm_provider = \"pollinations\"' | Set-Content '%INSTALL_DIR%\config.toml'"
    )
) else (
    echo Configuracao existente mantida ^(%INSTALL_DIR%\config.toml^).
)

rem ---------- Fase 5: icone e atalho na area de trabalho ----------
echo Criando icone e atalho na Area de Trabalho...
set "PS1=%TEMP%\mpt_atalho.ps1"
del "%PS1%" 2>nul
echo Add-Type -AssemblyName System.Drawing>> "%PS1%"
echo $d='%INSTALL_DIR%'>> "%PS1%"
echo $bmp=New-Object System.Drawing.Bitmap 64,64>> "%PS1%"
echo $g=[System.Drawing.Graphics]::FromImage($bmp)>> "%PS1%"
echo $g.SmoothingMode='AntiAlias'>> "%PS1%"
echo $g.Clear([System.Drawing.Color]::FromArgb(255,16,185,129))>> "%PS1%"
echo $pts=[System.Drawing.Point[]]@((New-Object System.Drawing.Point 24,16),(New-Object System.Drawing.Point 24,48),(New-Object System.Drawing.Point 50,32))>> "%PS1%"
echo $g.FillPolygon([System.Drawing.Brushes]::White,$pts)>> "%PS1%"
echo $g.Dispose()>> "%PS1%"
echo $ico=[System.Drawing.Icon]::FromHandle($bmp.GetHicon())>> "%PS1%"
echo $fs=[System.IO.File]::Create("$d\mpt.ico")>> "%PS1%"
echo $ico.Save($fs)>> "%PS1%"
echo $fs.Close()>> "%PS1%"
echo $ws=New-Object -ComObject WScript.Shell>> "%PS1%"
echo $desktop=[Environment]::GetFolderPath('Desktop')>> "%PS1%"
echo $lnk=$ws.CreateShortcut("$desktop\MoneyPrinterTurbo.lnk")>> "%PS1%"
echo $lnk.TargetPath="$d\webui.bat">> "%PS1%"
echo $lnk.WorkingDirectory=$d>> "%PS1%"
echo $lnk.IconLocation="$d\mpt.ico">> "%PS1%"
echo $lnk.Description='MoneyPrinterTurbo - Gerador de videos com IA'>> "%PS1%"
echo $lnk.Save()>> "%PS1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
del "%PS1%" 2>nul
if exist "%USERPROFILE%\Desktop\MoneyPrinterTurbo.bat" del "%USERPROFILE%\Desktop\MoneyPrinterTurbo.bat"
echo Icone "MoneyPrinterTurbo" (play verde) criado na Area de Trabalho.

rem ---------- Fase 6: iniciar ----------
echo.
echo ==========================================================
echo  INSTALACAO CONCLUIDA!
echo.
echo  A interface visual vai abrir agora no navegador.
echo  Endereco: http://127.0.0.1:8501
echo.
echo  Dica: na interface, troque o idioma para Portugues no
echo  topo e escolha a voz pt-BR-FranciscaNeural.
echo  Para abrir de novo no futuro, use o icone verde
echo  "MoneyPrinterTurbo" na sua Area de Trabalho.
echo ==========================================================
echo.
pause
start "" http://127.0.0.1:8501
call "%INSTALL_DIR%\webui.bat"
