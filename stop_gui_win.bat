@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PID_FILE=%SCRIPT_DIR%.dialup_gui.pid"

if not exist "%PID_FILE%" (
  echo PID file not found: %PID_FILE%
  echo If GUI is running manually, close it from window title bar.
  exit /b 1
)

set /p PID=<"%PID_FILE%"
taskkill /PID %PID% /T /F
if %errorlevel% neq 0 (
  echo Failed to stop PID %PID%. It may already be closed.
  del "%PID_FILE%" >nul 2>nul
  exit /b 1
)

del "%PID_FILE%" >nul 2>nul
echo Dial-Up GUI stopped.
