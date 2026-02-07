@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

for /f %%I in ('powershell -NoProfile -Command "$p = Start-Process -FilePath py -ArgumentList '-3w','\"%SCRIPT_DIR%dialup_gui.py\"' -PassThru; $p.Id"') do set "PID=%%I"

echo %PID%>"%SCRIPT_DIR%.dialup_gui.pid"
echo Dial-Up GUI started. PID=%PID%
