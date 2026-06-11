@echo off
chcp 65001 >nul
title MoneyPrinterTurbo - Servidor para iPhone/iPad
setlocal

rem ============================================================
rem  Inicia o MoneyPrinterTurbo acessivel pelo iPhone/iPad
rem  que estiver na MESMA rede Wi-Fi deste computador.
rem  Requisito: ja ter rodado o instalar-moneyprinterturbo.bat
rem ============================================================

set "INSTALL_DIR=%USERPROFILE%\MoneyPrinterTurbo"

if not exist "%INSTALL_DIR%\webui\Main.py" (
    echo [ERRO] MoneyPrinterTurbo nao encontrado em %INSTALL_DIR%.
    echo Rode primeiro o instalar-moneyprinterturbo.bat
    pause
    exit /b 1
)

rem Descobre o IP local deste computador na rede Wi-Fi
set "LOCAL_IP="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1).IPAddress"`) do set "LOCAL_IP=%%I"

if not defined LOCAL_IP (
    echo [AVISO] Nao consegui detectar o IP local automaticamente.
    echo Descubra com o comando: ipconfig  ^(campo "Endereco IPv4"^)
    set "LOCAL_IP=SEU-IP-AQUI"
)

echo ==========================================================
echo   SERVIDOR PARA IPHONE/IPAD
echo.
echo   1. Conecte o iPhone na MESMA rede Wi-Fi deste PC.
echo   2. Abra o Safari no iPhone e acesse:
echo.
echo         http://%LOCAL_IP%:8501
echo.
echo   3. Para virar "aplicativo": toque em Compartilhar
echo      e depois "Adicionar a Tela de Inicio".
echo.
echo   OBS: se o Windows perguntar sobre o Firewall,
echo   clique em "Permitir acesso" ^(rede privada^).
echo   Mantenha esta janela aberta enquanto usa no iPhone.
echo ==========================================================
echo.

rem Faz a WebUI escutar em todas as interfaces da rede local
set "MPT_WEBUI_HOST=0.0.0.0"
cd /d "%INSTALL_DIR%"
call webui.bat
