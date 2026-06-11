@echo off
chcp 65001 >/dev/null
title Instalar Modo Aplicativo - MoneyPrinterTurbo
setlocal

rem ============================================================
rem  MODO APLICATIVO do MoneyPrinterTurbo
rem  - Sem janela preta: servidor roda invisivel
rem  - Tela de carregamento + janela propria (estilo app)
rem  - Icone na bandeja do sistema com menu (abrir/videos/sair)
rem  Requisito: ja ter rodado o instalar-moneyprinterturbo.bat
rem ============================================================

set "INSTALL_DIR=%USERPROFILE%\MoneyPrinterTurbo"

if not exist "%INSTALL_DIR%\.venv\Scripts\python.exe" (
    echo [ERRO] MoneyPrinterTurbo nao encontrado em %INSTALL_DIR%.
    echo Rode primeiro o instalar-moneyprinterturbo.bat
    pause
    exit /b 1
)

echo Instalando o Modo Aplicativo...

rem ---------- Grava os componentes do aplicativo ----------
del "%TEMP%\mpt_app_ps1.b64" 2>nul
echo IyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09>> "%TEMP%\mpt_app_ps1.b64"
echo PT09PT0KIyAgTW9uZXlQcmludGVyVHVyYm8gLSBNb2RvIEFwbGljYXRpdm8KIyAgLSBJbmljaWEg>> "%TEMP%\mpt_app_ps1.b64"
echo byBzZXJ2aWRvciBpbnZpc2l2ZWwgZW0gc2VndW5kbyBwbGFubwojICAtIE1vc3RyYSB0ZWxhIGRl>> "%TEMP%\mpt_app_ps1.b64"
echo IGNhcnJlZ2FtZW50bwojICAtIEFicmUgYSBpbnRlcmZhY2UgZW0gamFuZWxhIHByb3ByaWEgKGVz>> "%TEMP%\mpt_app_ps1.b64"
echo dGlsbyBhcGxpY2F0aXZvKQojICAtIEZpY2EgbmEgYmFuZGVqYSBkbyBzaXN0ZW1hIChpY29uZSB2>> "%TEMP%\mpt_app_ps1.b64"
echo ZXJkZSBwZXJ0byBkbyByZWxvZ2lvKQojID09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09>> "%TEMP%\mpt_app_ps1.b64"
echo PT09PT09PT09PT09PT09PT09PT09PT09PT09PQokRXJyb3JBY3Rpb25QcmVmZXJlbmNlID0gJ1Np>> "%TEMP%\mpt_app_ps1.b64"
echo bGVudGx5Q29udGludWUnCkFkZC1UeXBlIC1Bc3NlbWJseU5hbWUgU3lzdGVtLldpbmRvd3MuRm9y>> "%TEMP%\mpt_app_ps1.b64"
echo bXMKQWRkLVR5cGUgLUFzc2VtYmx5TmFtZSBTeXN0ZW0uRHJhd2luZwoKJHNjcmlwdDppbnN0YWxs>> "%TEMP%\mpt_app_ps1.b64"
echo RGlyID0gSm9pbi1QYXRoICRlbnY6VVNFUlBST0ZJTEUgJ01vbmV5UHJpbnRlclR1cmJvJwokcHl0>> "%TEMP%\mpt_app_ps1.b64"
echo aG9uID0gSm9pbi1QYXRoICRzY3JpcHQ6aW5zdGFsbERpciAnLnZlbnZcU2NyaXB0c1xweXRob24u>> "%TEMP%\mpt_app_ps1.b64"
echo ZXhlJwokcGlkRmlsZSA9IEpvaW4tUGF0aCAkc2NyaXB0Omluc3RhbGxEaXIgJy5hcHBfc2VydmVy>> "%TEMP%\mpt_app_ps1.b64"
echo LnBpZCcKCmZ1bmN0aW9uIFNob3ctRXJyb3IoW3N0cmluZ10kbXNnKSB7CiAgW1N5c3RlbS5XaW5k>> "%TEMP%\mpt_app_ps1.b64"
echo b3dzLkZvcm1zLk1lc3NhZ2VCb3hdOjpTaG93KCRtc2csICdNb25leVByaW50ZXJUdXJibycsICdP>> "%TEMP%\mpt_app_ps1.b64"
echo SycsICdFcnJvcicpIHwgT3V0LU51bGwKfQoKZnVuY3Rpb24gVGVzdC1Qb3J0T3BlbihbaW50XSRw>> "%TEMP%\mpt_app_ps1.b64"
echo KSB7CiAgJGMgPSBOZXctT2JqZWN0IFN5c3RlbS5OZXQuU29ja2V0cy5UY3BDbGllbnQKICB0cnkg>> "%TEMP%\mpt_app_ps1.b64"
echo eyAkYy5Db25uZWN0KCcxMjcuMC4wLjEnLCAkcCk7ICRjLkNsb3NlKCk7IHJldHVybiAkdHJ1ZSB9>> "%TEMP%\mpt_app_ps1.b64"
echo IGNhdGNoIHsgcmV0dXJuICRmYWxzZSB9IGZpbmFsbHkgeyAkYy5EaXNwb3NlKCkgfQp9CgpmdW5j>> "%TEMP%\mpt_app_ps1.b64"
echo dGlvbiBPcGVuLUFwcFdpbmRvdyhbc3RyaW5nXSR1KSB7CiAgJGVkZ2UxID0gIiR7ZW52OlByb2dy>> "%TEMP%\mpt_app_ps1.b64"
echo YW1GaWxlcyh4ODYpfVxNaWNyb3NvZnRcRWRnZVxBcHBsaWNhdGlvblxtc2VkZ2UuZXhlIgogICRl>> "%TEMP%\mpt_app_ps1.b64"
echo ZGdlMiA9ICIkZW52OlByb2dyYW1GaWxlc1xNaWNyb3NvZnRcRWRnZVxBcHBsaWNhdGlvblxtc2Vk>> "%TEMP%\mpt_app_ps1.b64"
echo Z2UuZXhlIgogICRjaHJvbWUxID0gIiRlbnY6UHJvZ3JhbUZpbGVzXEdvb2dsZVxDaHJvbWVcQXBw>> "%TEMP%\mpt_app_ps1.b64"
echo bGljYXRpb25cY2hyb21lLmV4ZSIKICAkY2hyb21lMiA9ICIke2VudjpQcm9ncmFtRmlsZXMoeDg2>> "%TEMP%\mpt_app_ps1.b64"
echo KX1cR29vZ2xlXENocm9tZVxBcHBsaWNhdGlvblxjaHJvbWUuZXhlIgogIGlmIChUZXN0LVBhdGgg>> "%TEMP%\mpt_app_ps1.b64"
echo JGVkZ2UxKSB7IFN0YXJ0LVByb2Nlc3MgJGVkZ2UxIC1Bcmd1bWVudExpc3QgIi0tYXBwPSR1IiB9>> "%TEMP%\mpt_app_ps1.b64"
echo CiAgZWxzZWlmIChUZXN0LVBhdGggJGVkZ2UyKSB7IFN0YXJ0LVByb2Nlc3MgJGVkZ2UyIC1Bcmd1>> "%TEMP%\mpt_app_ps1.b64"
echo bWVudExpc3QgIi0tYXBwPSR1IiB9CiAgZWxzZWlmIChUZXN0LVBhdGggJGNocm9tZTEpIHsgU3Rh>> "%TEMP%\mpt_app_ps1.b64"
echo cnQtUHJvY2VzcyAkY2hyb21lMSAtQXJndW1lbnRMaXN0ICItLWFwcD0kdSIgfQogIGVsc2VpZiAo>> "%TEMP%\mpt_app_ps1.b64"
echo VGVzdC1QYXRoICRjaHJvbWUyKSB7IFN0YXJ0LVByb2Nlc3MgJGNocm9tZTIgLUFyZ3VtZW50TGlz>> "%TEMP%\mpt_app_ps1.b64"
echo dCAiLS1hcHA9JHUiIH0KICBlbHNlIHsgU3RhcnQtUHJvY2VzcyAkdSB9Cn0KCmZ1bmN0aW9uIE5l>> "%TEMP%\mpt_app_ps1.b64"
echo dy1NcHRJY29uIHsKICAkYm1wID0gTmV3LU9iamVjdCBTeXN0ZW0uRHJhd2luZy5CaXRtYXAgMzIs>> "%TEMP%\mpt_app_ps1.b64"
echo MzIKICAkZyA9IFtTeXN0ZW0uRHJhd2luZy5HcmFwaGljc106OkZyb21JbWFnZSgkYm1wKQogICRn>> "%TEMP%\mpt_app_ps1.b64"
echo LlNtb290aGluZ01vZGUgPSAnQW50aUFsaWFzJwogICRnLkNsZWFyKFtTeXN0ZW0uRHJhd2luZy5D>> "%TEMP%\mpt_app_ps1.b64"
echo b2xvcl06OkZyb21BcmdiKDI1NSwxNiwxODUsMTI5KSkKICAkcHRzID0gW1N5c3RlbS5EcmF3aW5n>> "%TEMP%\mpt_app_ps1.b64"
echo LlBvaW50W11dQCgoTmV3LU9iamVjdCBTeXN0ZW0uRHJhd2luZy5Qb2ludCAxMSw3KSwoTmV3LU9i>> "%TEMP%\mpt_app_ps1.b64"
echo amVjdCBTeXN0ZW0uRHJhd2luZy5Qb2ludCAxMSwyNSksKE5ldy1PYmplY3QgU3lzdGVtLkRyYXdp>> "%TEMP%\mpt_app_ps1.b64"
echo bmcuUG9pbnQgMjYsMTYpKQogICRnLkZpbGxQb2x5Z29uKFtTeXN0ZW0uRHJhd2luZy5CcnVzaGVz>> "%TEMP%\mpt_app_ps1.b64"
echo XTo6V2hpdGUsICRwdHMpCiAgJGcuRGlzcG9zZSgpCiAgcmV0dXJuIFtTeXN0ZW0uRHJhd2luZy5J>> "%TEMP%\mpt_app_ps1.b64"
echo Y29uXTo6RnJvbUhhbmRsZSgkYm1wLkdldEhpY29uKCkpCn0KCiMgLS0tLS0tLS0tLSBQcm9ncmFt>> "%TEMP%\mpt_app_ps1.b64"
echo YSBpbnN0YWxhZG8/IC0tLS0tLS0tLS0KaWYgKC1ub3QgKFRlc3QtUGF0aCAkcHl0aG9uKSkgewog>> "%TEMP%\mpt_app_ps1.b64"
echo IFNob3ctRXJyb3IgKCJPIE1vbmV5UHJpbnRlclR1cmJvIG5hbyBmb2kgZW5jb250cmFkbyBlbSAi>> "%TEMP%\mpt_app_ps1.b64"
echo ICsgJHNjcmlwdDppbnN0YWxsRGlyICsgIi5gbmBuRXhlY3V0ZSBwcmltZWlybyBvIGluc3RhbGFy>> "%TEMP%\mpt_app_ps1.b64"
echo LW1vbmV5cHJpbnRlcnR1cmJvLmJhdCIpCiAgZXhpdCAxCn0KCiMgLS0tLS0tLS0tLSBKYSBlc3Rh>> "%TEMP%\mpt_app_ps1.b64"
echo IHJvZGFuZG8/IEVudGFvIHNvIGFicmUgYSBqYW5lbGEgLS0tLS0tLS0tLQppZiAoVGVzdC1QYXRo>> "%TEMP%\mpt_app_ps1.b64"
echo ICRwaWRGaWxlKSB7CiAgJHBhcnRzID0gKChHZXQtQ29udGVudCAkcGlkRmlsZSAtRmlyc3QgMSkg>> "%TEMP%\mpt_app_ps1.b64"
echo LXNwbGl0ICcgJykKICAkb2xkUGlkID0gMDsgJG9sZFBvcnQgPSAwCiAgW3ZvaWRdW2ludF06OlRy>> "%TEMP%\mpt_app_ps1.b64"
echo eVBhcnNlKCRwYXJ0c1swXSwgW3JlZl0kb2xkUGlkKQogIGlmICgkcGFydHMuQ291bnQgLWd0IDEp>> "%TEMP%\mpt_app_ps1.b64"
echo IHsgW3ZvaWRdW2ludF06OlRyeVBhcnNlKCRwYXJ0c1sxXSwgW3JlZl0kb2xkUG9ydCkgfQogICRh>> "%TEMP%\mpt_app_ps1.b64"
echo bGl2ZSA9ICRudWxsCiAgaWYgKCRvbGRQaWQgLWd0IDApIHsgJGFsaXZlID0gR2V0LVByb2Nlc3Mg>> "%TEMP%\mpt_app_ps1.b64"
echo LUlkICRvbGRQaWQgLUVycm9yQWN0aW9uIFNpbGVudGx5Q29udGludWUgfQogIGlmICgkYWxpdmUg>> "%TEMP%\mpt_app_ps1.b64"
echo LWFuZCAkb2xkUG9ydCAtZ3QgMCAtYW5kIChUZXN0LVBvcnRPcGVuICRvbGRQb3J0KSkgewogICAg>> "%TEMP%\mpt_app_ps1.b64"
echo T3Blbi1BcHBXaW5kb3cgKCJodHRwOi8vMTI3LjAuMC4xOiIgKyAkb2xkUG9ydCkKICAgIGV4aXQg>> "%TEMP%\mpt_app_ps1.b64"
echo MAogIH0KICBSZW1vdmUtSXRlbSAkcGlkRmlsZSAtRm9yY2UKfQoKIyAtLS0tLS0tLS0tIEVzY29s>> "%TEMP%\mpt_app_ps1.b64"
echo aGUgdW1hIHBvcnRhIGxpdnJlIC0tLS0tLS0tLS0KJHNjcmlwdDpwb3J0ID0gMApmb3JlYWNoICgk>> "%TEMP%\mpt_app_ps1.b64"
echo cCBpbiA4NTAxLi44NTk5KSB7IGlmICgtbm90IChUZXN0LVBvcnRPcGVuICRwKSkgeyAkc2NyaXB0>> "%TEMP%\mpt_app_ps1.b64"
echo OnBvcnQgPSAkcDsgYnJlYWsgfSB9CmlmICgkc2NyaXB0OnBvcnQgLWVxIDApIHsgU2hvdy1FcnJv>> "%TEMP%\mpt_app_ps1.b64"
echo ciAnTmVuaHVtYSBwb3J0YSBsaXZyZSBlbmNvbnRyYWRhICg4NTAxLTg1OTkpLic7IGV4aXQgMSB9>> "%TEMP%\mpt_app_ps1.b64"
echo CgojIC0tLS0tLS0tLS0gVGVsYSBkZSBjYXJyZWdhbWVudG8gLS0tLS0tLS0tLQokc3BsYXNoID0g>> "%TEMP%\mpt_app_ps1.b64"
echo TmV3LU9iamVjdCBTeXN0ZW0uV2luZG93cy5Gb3Jtcy5Gb3JtCiRzcGxhc2guRm9ybUJvcmRlclN0>> "%TEMP%\mpt_app_ps1.b64"
echo eWxlID0gJ05vbmUnCiRzcGxhc2guU3RhcnRQb3NpdGlvbiA9ICdDZW50ZXJTY3JlZW4nCiRzcGxh>> "%TEMP%\mpt_app_ps1.b64"
echo c2guU2l6ZSA9IE5ldy1PYmplY3QgU3lzdGVtLkRyYXdpbmcuU2l6ZSg0NDAsIDE1MCkKJHNwbGFz>> "%TEMP%\mpt_app_ps1.b64"
echo aC5CYWNrQ29sb3IgPSBbU3lzdGVtLkRyYXdpbmcuQ29sb3JdOjpGcm9tQXJnYigyNTUsIDE3LCAy>> "%TEMP%\mpt_app_ps1.b64"
echo NCwgMzkpCiRzcGxhc2guVG9wTW9zdCA9ICR0cnVlCiRsYmwgPSBOZXctT2JqZWN0IFN5c3RlbS5X>> "%TEMP%\mpt_app_ps1.b64"
echo aW5kb3dzLkZvcm1zLkxhYmVsCiRsYmwuVGV4dCA9ICdJbmljaWFuZG8gbyBNb25leVByaW50ZXJU>> "%TEMP%\mpt_app_ps1.b64"
echo dXJiby4uLicKJGxibC5Gb3JlQ29sb3IgPSBbU3lzdGVtLkRyYXdpbmcuQ29sb3JdOjpXaGl0ZQok>> "%TEMP%\mpt_app_ps1.b64"
echo bGJsLkZvbnQgPSBOZXctT2JqZWN0IFN5c3RlbS5EcmF3aW5nLkZvbnQoJ1NlZ29lIFVJJywgMTMs>> "%TEMP%\mpt_app_ps1.b64"
echo IFtTeXN0ZW0uRHJhd2luZy5Gb250U3R5bGVdOjpCb2xkKQokbGJsLlRleHRBbGlnbiA9ICdNaWRk>> "%TEMP%\mpt_app_ps1.b64"
echo bGVDZW50ZXInCiRsYmwuRG9jayA9ICdUb3AnCiRsYmwuSGVpZ2h0ID0gNjQKJHN1YiA9IE5ldy1P>> "%TEMP%\mpt_app_ps1.b64"
echo YmplY3QgU3lzdGVtLldpbmRvd3MuRm9ybXMuTGFiZWwKJHN1Yi5UZXh0ID0gJ1ByZXBhcmFuZG8g>> "%TEMP%\mpt_app_ps1.b64"
echo byBlc3R1ZGlvIGRlIHZpZGVvcy4gSXNzbyBsZXZhIGFsZ3VucyBzZWd1bmRvcy4nCiRzdWIuRm9y>> "%TEMP%\mpt_app_ps1.b64"
echo ZUNvbG9yID0gW1N5c3RlbS5EcmF3aW5nLkNvbG9yXTo6RnJvbUFyZ2IoMjU1LCAxNTYsIDE2Mywg>> "%TEMP%\mpt_app_ps1.b64"
echo MTc1KQokc3ViLkZvbnQgPSBOZXctT2JqZWN0IFN5c3RlbS5EcmF3aW5nLkZvbnQoJ1NlZ29lIFVJ>> "%TEMP%\mpt_app_ps1.b64"
echo JywgOSkKJHN1Yi5UZXh0QWxpZ24gPSAnTWlkZGxlQ2VudGVyJwokc3ViLkRvY2sgPSAnVG9wJwok>> "%TEMP%\mpt_app_ps1.b64"
echo c3ViLkhlaWdodCA9IDM0CiRiYXIgPSBOZXctT2JqZWN0IFN5c3RlbS5XaW5kb3dzLkZvcm1zLlBy>> "%TEMP%\mpt_app_ps1.b64"
echo b2dyZXNzQmFyCiRiYXIuU3R5bGUgPSAnTWFycXVlZScKJGJhci5NYXJxdWVlQW5pbWF0aW9uU3Bl>> "%TEMP%\mpt_app_ps1.b64"
echo ZWQgPSAyNQokYmFyLkRvY2sgPSAnQm90dG9tJwokYmFyLkhlaWdodCA9IDE2CiRzcGxhc2guQ29u>> "%TEMP%\mpt_app_ps1.b64"
echo dHJvbHMuQWRkKCRzdWIpCiRzcGxhc2guQ29udHJvbHMuQWRkKCRsYmwpCiRzcGxhc2guQ29udHJv>> "%TEMP%\mpt_app_ps1.b64"
echo bHMuQWRkKCRiYXIpCiRzcGxhc2guU2hvdygpCltTeXN0ZW0uV2luZG93cy5Gb3Jtcy5BcHBsaWNh>> "%TEMP%\mpt_app_ps1.b64"
echo dGlvbl06OkRvRXZlbnRzKCkKCiMgLS0tLS0tLS0tLSBJbmljaWEgbyBzZXJ2aWRvciBpbnZpc2l2>> "%TEMP%\mpt_app_ps1.b64"
echo ZWwgLS0tLS0tLS0tLQokZW52OlBZVEhPTlBBVEggPSAkc2NyaXB0Omluc3RhbGxEaXIKJG1haW5Q>> "%TEMP%\mpt_app_ps1.b64"
echo eSA9IEpvaW4tUGF0aCAkc2NyaXB0Omluc3RhbGxEaXIgJ3dlYnVpXE1haW4ucHknCiRzcnZBcmdz>> "%TEMP%\mpt_app_ps1.b64"
echo ID0gQCgnLW0nLCdzdHJlYW1saXQnLCdydW4nLCAkbWFpblB5LAogICctLXNlcnZlci5hZGRyZXNz>> "%TEMP%\mpt_app_ps1.b64"
echo PTEyNy4wLjAuMScsICgnLS1zZXJ2ZXIucG9ydD0nICsgJHNjcmlwdDpwb3J0KSwKICAnLS1icm93>> "%TEMP%\mpt_app_ps1.b64"
echo c2VyLmdhdGhlclVzYWdlU3RhdHM9RmFsc2UnLCAnLS1zZXJ2ZXIuaGVhZGxlc3M9VHJ1ZScpCiRz>> "%TEMP%\mpt_app_ps1.b64"
echo Y3JpcHQ6c2VydmVyID0gU3RhcnQtUHJvY2VzcyAtRmlsZVBhdGggJHB5dGhvbiAtQXJndW1lbnRM>> "%TEMP%\mpt_app_ps1.b64"
echo aXN0ICRzcnZBcmdzIC1Xb3JraW5nRGlyZWN0b3J5ICRzY3JpcHQ6aW5zdGFsbERpciAtV2luZG93>> "%TEMP%\mpt_app_ps1.b64"
echo U3R5bGUgSGlkZGVuIC1QYXNzVGhydQoKIyAtLS0tLS0tLS0tIEVzcGVyYSBmaWNhciBwcm9udG8g>> "%TEMP%\mpt_app_ps1.b64"
echo KGF0ZSAxMjAgc2VndW5kb3MpIC0tLS0tLS0tLS0KJHJlYWR5ID0gJGZhbHNlCmZvciAoJGkgPSAw>> "%TEMP%\mpt_app_ps1.b64"
echo OyAkaSAtbHQgMjQwOyAkaSsrKSB7CiAgU3RhcnQtU2xlZXAgLU1pbGxpc2Vjb25kcyA1MDAKICBb>> "%TEMP%\mpt_app_ps1.b64"
echo U3lzdGVtLldpbmRvd3MuRm9ybXMuQXBwbGljYXRpb25dOjpEb0V2ZW50cygpCiAgaWYgKCRzY3Jp>> "%TEMP%\mpt_app_ps1.b64"
echo cHQ6c2VydmVyLkhhc0V4aXRlZCkgeyBicmVhayB9CiAgaWYgKFRlc3QtUG9ydE9wZW4gJHNjcmlw>> "%TEMP%\mpt_app_ps1.b64"
echo dDpwb3J0KSB7ICRyZWFkeSA9ICR0cnVlOyBicmVhayB9Cn0KJHNwbGFzaC5DbG9zZSgpCgppZiAo>> "%TEMP%\mpt_app_ps1.b64"
echo LW5vdCAkcmVhZHkpIHsKICBpZiAoJHNjcmlwdDpzZXJ2ZXIgLWFuZCAtbm90ICRzY3JpcHQ6c2Vy>> "%TEMP%\mpt_app_ps1.b64"
echo dmVyLkhhc0V4aXRlZCkgeyAmIHRhc2traWxsIC9QSUQgJHNjcmlwdDpzZXJ2ZXIuSWQgL1QgL0Yg>> "%TEMP%\mpt_app_ps1.b64"
echo fCBPdXQtTnVsbCB9CiAgU2hvdy1FcnJvciAoIk8gc2Vydmlkb3IgbmFvIGNvbnNlZ3VpdSBpbmlj>> "%TEMP%\mpt_app_ps1.b64"
echo aWFyLmBuYG5QYXJhIHZlciBvIG1vdGl2bywgYWJyYSBhIHBhc3RhICIgKyAkc2NyaXB0Omluc3Rh>> "%TEMP%\mpt_app_ps1.b64"
echo bGxEaXIgKyAiIGUgZXhlY3V0ZSBvIHdlYnVpLmJhdCIpCiAgZXhpdCAxCn0KClNldC1Db250ZW50>> "%TEMP%\mpt_app_ps1.b64"
echo IC1QYXRoICRwaWRGaWxlIC1WYWx1ZSAoJHNjcmlwdDpzZXJ2ZXIuSWQuVG9TdHJpbmcoKSArICcg>> "%TEMP%\mpt_app_ps1.b64"
echo JyArICRzY3JpcHQ6cG9ydC5Ub1N0cmluZygpKQokc2NyaXB0OnVybCA9ICdodHRwOi8vMTI3LjAu>> "%TEMP%\mpt_app_ps1.b64"
echo MC4xOicgKyAkc2NyaXB0OnBvcnQKCiMgLS0tLS0tLS0tLSBBYnJlIGEgaW50ZXJmYWNlIGVtIGph>> "%TEMP%\mpt_app_ps1.b64"
echo bmVsYSBwcm9wcmlhIC0tLS0tLS0tLS0KT3Blbi1BcHBXaW5kb3cgJHNjcmlwdDp1cmwKCiMgLS0t>> "%TEMP%\mpt_app_ps1.b64"
echo LS0tLS0tLSBJY29uZSBuYSBiYW5kZWphIGRvIHNpc3RlbWEgLS0tLS0tLS0tLQokc2NyaXB0OnRy>> "%TEMP%\mpt_app_ps1.b64"
echo YXkgPSBOZXctT2JqZWN0IFN5c3RlbS5XaW5kb3dzLkZvcm1zLk5vdGlmeUljb24KJHNjcmlwdDp0>> "%TEMP%\mpt_app_ps1.b64"
echo cmF5Lkljb24gPSBOZXctTXB0SWNvbgokc2NyaXB0OnRyYXkuVGV4dCA9ICdNb25leVByaW50ZXJU>> "%TEMP%\mpt_app_ps1.b64"
echo dXJibyAtIGJvdGFvIGRpcmVpdG8gcGFyYSBvcGNvZXMnCiRzY3JpcHQ6dHJheS5WaXNpYmxlID0g>> "%TEMP%\mpt_app_ps1.b64"
echo JHRydWUKCiRtZW51ID0gTmV3LU9iamVjdCBTeXN0ZW0uV2luZG93cy5Gb3Jtcy5Db250ZXh0TWVu>> "%TEMP%\mpt_app_ps1.b64"
echo dVN0cmlwCiRtaU9wZW4gICA9ICRtZW51Lkl0ZW1zLkFkZCgnQWJyaXIgbyBNb25leVByaW50ZXJU>> "%TEMP%\mpt_app_ps1.b64"
echo dXJibycpCiRtaVZpZGVvcyA9ICRtZW51Lkl0ZW1zLkFkZCgnUGFzdGEgZG9zIHZpZGVvcyBwcm9u>> "%TEMP%\mpt_app_ps1.b64"
echo dG9zJykKW3ZvaWRdJG1lbnUuSXRlbXMuQWRkKCctJykKJG1pRXhpdCAgID0gJG1lbnUuSXRlbXMu>> "%TEMP%\mpt_app_ps1.b64"
echo QWRkKCdFbmNlcnJhciBvIE1vbmV5UHJpbnRlclR1cmJvJykKJHNjcmlwdDp0cmF5LkNvbnRleHRN>> "%TEMP%\mpt_app_ps1.b64"
echo ZW51U3RyaXAgPSAkbWVudQoKJG1pT3Blbi5hZGRfQ2xpY2soeyBPcGVuLUFwcFdpbmRvdyAkc2Ny>> "%TEMP%\mpt_app_ps1.b64"
echo aXB0OnVybCB9KQokc2NyaXB0OnRyYXkuYWRkX0RvdWJsZUNsaWNrKHsgT3Blbi1BcHBXaW5kb3cg>> "%TEMP%\mpt_app_ps1.b64"
echo JHNjcmlwdDp1cmwgfSkKJG1pVmlkZW9zLmFkZF9DbGljayh7CiAgJHRhc2tzID0gSm9pbi1QYXRo>> "%TEMP%\mpt_app_ps1.b64"
echo ICRzY3JpcHQ6aW5zdGFsbERpciAnc3RvcmFnZVx0YXNrcycKICBpZiAoLW5vdCAoVGVzdC1QYXRo>> "%TEMP%\mpt_app_ps1.b64"
echo ICR0YXNrcykpIHsgTmV3LUl0ZW0gLUl0ZW1UeXBlIERpcmVjdG9yeSAtUGF0aCAkdGFza3MgLUZv>> "%TEMP%\mpt_app_ps1.b64"
echo cmNlIHwgT3V0LU51bGwgfQogIFN0YXJ0LVByb2Nlc3MgZXhwbG9yZXIuZXhlICR0YXNrcwp9KQok>> "%TEMP%\mpt_app_ps1.b64"
echo bWlFeGl0LmFkZF9DbGljayh7CiAgJHNjcmlwdDp0cmF5LlZpc2libGUgPSAkZmFsc2UKICAmIHRh>> "%TEMP%\mpt_app_ps1.b64"
echo c2traWxsIC9QSUQgJHNjcmlwdDpzZXJ2ZXIuSWQgL1QgL0YgfCBPdXQtTnVsbAogIFJlbW92ZS1J>> "%TEMP%\mpt_app_ps1.b64"
echo dGVtIChKb2luLVBhdGggJHNjcmlwdDppbnN0YWxsRGlyICcuYXBwX3NlcnZlci5waWQnKSAtRm9y>> "%TEMP%\mpt_app_ps1.b64"
echo Y2UKICBbU3lzdGVtLldpbmRvd3MuRm9ybXMuQXBwbGljYXRpb25dOjpFeGl0KCkKfSkKCiRzY3Jp>> "%TEMP%\mpt_app_ps1.b64"
echo cHQ6dHJheS5TaG93QmFsbG9vblRpcCg1MDAwLCAnTW9uZXlQcmludGVyVHVyYm8gZXN0YSByb2Rh>> "%TEMP%\mpt_app_ps1.b64"
echo bmRvJywKICAnQSBpbnRlcmZhY2UgYWJyaXUgZW0gdW1hIGphbmVsYSBwcm9wcmlhLiBFdSBmaWNv>> "%TEMP%\mpt_app_ps1.b64"
echo IGFxdWkgbmEgYmFuZGVqYSAoaWNvbmUgdmVyZGUsIHBlcnRvIGRvIHJlbG9naW8pLiBCb3RhbyBk>> "%TEMP%\mpt_app_ps1.b64"
echo aXJlaXRvIHBhcmEgb3Bjb2VzLicsICdJbmZvJykKCltTeXN0ZW0uV2luZG93cy5Gb3Jtcy5BcHBs>> "%TEMP%\mpt_app_ps1.b64"
echo aWNhdGlvbl06OlJ1bigpCg==>> "%TEMP%\mpt_app_ps1.b64"
certutil -f -decode "%TEMP%\mpt_app_ps1.b64" "%INSTALL_DIR%\MoneyPrinterTurboApp.ps1" >/dev/null
del "%TEMP%\mpt_app_ps1.b64" 2>/dev/null

del "%TEMP%\mpt_app_vbs.b64" 2>nul
echo JyBJbmljaWEgbyBNb25leVByaW50ZXJUdXJibyBlbSBtb2RvIGFwbGljYXRpdm8sIHNlbSBqYW5l>> "%TEMP%\mpt_app_vbs.b64"
echo bGEgcHJldGEuClNldCBmc28gPSBDcmVhdGVPYmplY3QoIlNjcmlwdGluZy5GaWxlU3lzdGVtT2Jq>> "%TEMP%\mpt_app_vbs.b64"
echo ZWN0IikKYXBwRGlyID0gZnNvLkdldFBhcmVudEZvbGRlck5hbWUoV1NjcmlwdC5TY3JpcHRGdWxs>> "%TEMP%\mpt_app_vbs.b64"
echo TmFtZSkKU2V0IHNoID0gQ3JlYXRlT2JqZWN0KCJXU2NyaXB0LlNoZWxsIikKc2guUnVuICJwb3dl>> "%TEMP%\mpt_app_vbs.b64"
echo cnNoZWxsLmV4ZSAtTm9Qcm9maWxlIC1FeGVjdXRpb25Qb2xpY3kgQnlwYXNzIC1XaW5kb3dTdHls>> "%TEMP%\mpt_app_vbs.b64"
echo ZSBIaWRkZW4gLUZpbGUgIiIiICYgYXBwRGlyICYgIlxNb25leVByaW50ZXJUdXJib0FwcC5wczEi>> "%TEMP%\mpt_app_vbs.b64"
echo IiIsIDAsIEZhbHNlCg==>> "%TEMP%\mpt_app_vbs.b64"
certutil -f -decode "%TEMP%\mpt_app_vbs.b64" "%INSTALL_DIR%\MoneyPrinterTurboApp.vbs" >/dev/null
del "%TEMP%\mpt_app_vbs.b64" 2>/dev/null

if not exist "%INSTALL_DIR%\MoneyPrinterTurboApp.ps1" (
    echo [ERRO] Falha ao gravar os componentes do aplicativo.
    pause
    exit /b 1
)

rem ---------- Cria o icone (play verde) ----------
set "PS1=%TEMP%\mpt_icone.ps1"
del "%PS1%" 2>/dev/null
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
echo $lnk.TargetPath="$env:WINDIR\System32\wscript.exe">> "%PS1%"
echo $lnk.Arguments="""$d\MoneyPrinterTurboApp.vbs""">> "%PS1%"
echo $lnk.WorkingDirectory=$d>> "%PS1%"
echo $lnk.IconLocation="$d\mpt.ico">> "%PS1%"
echo $lnk.Description='MoneyPrinterTurbo - Gerador de videos com IA'>> "%PS1%"
echo $lnk.Save()>> "%PS1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
del "%PS1%" 2>/dev/null

rem Remove atalhos antigos
if exist "%USERPROFILE%\Desktop\MoneyPrinterTurbo.bat" del "%USERPROFILE%\Desktop\MoneyPrinterTurbo.bat"

echo.
echo ==========================================================
echo  MODO APLICATIVO INSTALADO!
echo.
echo  A partir de agora, o icone verde "MoneyPrinterTurbo"
echo  na Area de Trabalho:
echo    - NAO abre mais janela preta
echo    - Mostra uma tela de carregamento
echo    - Abre a interface em janela propria, como um app
echo    - Fica na bandeja, perto do relogio (botao direito:
echo      Abrir / Pasta dos videos / Encerrar)
echo ==========================================================
echo.
choice /C SN /M "Quer abrir o MoneyPrinterTurbo agora? [S/N]"
if errorlevel 2 goto fim
start "" wscript.exe "%INSTALL_DIR%\MoneyPrinterTurboApp.vbs"
:fim
echo Ate logo!
timeout /t 3 >/dev/null
