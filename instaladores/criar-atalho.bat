@echo off
chcp 65001 >nul
title Criar atalho do MoneyPrinterTurbo
setlocal

rem ============================================================
rem  Cria um icone/atalho do MoneyPrinterTurbo na Area de
rem  Trabalho (atalho .lnk com icone proprio).
rem  Requisito: ja ter instalado com instalar-moneyprinterturbo.bat
rem ============================================================

set "INSTALL_DIR=%USERPROFILE%\MoneyPrinterTurbo"

if not exist "%INSTALL_DIR%\webui.bat" (
    echo [ERRO] MoneyPrinterTurbo nao encontrado em %INSTALL_DIR%.
    echo Rode primeiro o instalar-moneyprinterturbo.bat
    pause
    exit /b 1
)

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
set "PS_RESULT=%ERRORLEVEL%"
del "%PS1%" 2>nul

if not "%PS_RESULT%"=="0" (
    echo [ERRO] Falha ao criar o atalho. Veja as mensagens acima.
    pause
    exit /b 1
)

rem Remove o atalho antigo em formato .bat, se existir
if exist "%USERPROFILE%\Desktop\MoneyPrinterTurbo.bat" del "%USERPROFILE%\Desktop\MoneyPrinterTurbo.bat"

echo.
echo ==========================================================
echo  PRONTO!
echo.
echo  O icone "MoneyPrinterTurbo" (play verde) foi criado na
echo  sua Area de Trabalho.
echo.
echo  Duplo clique nele abre o servidor (janela preta - deixe
echo  aberta) e a interface fica em http://127.0.0.1:8501
echo  (confira o endereco exato exibido na janela).
echo ==========================================================
pause
