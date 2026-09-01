@echo off
cd /d "%~dp0"
:: Mata bot atual pela porta do single-instance lock
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:47591"') do taskkill /F /PID %%a 2>nul
timeout /t 2 /nobreak >nul
:: Inicia novo bot via VBS (janela invisivel)
cscript //nologo "%~dp0run_bot.vbs"
exit
