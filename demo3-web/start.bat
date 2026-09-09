@echo off
setlocal enabledelayedexpansion
title Baomi Agent
echo ============================================
echo   Baomi Agent - Starting...
echo ============================================
echo.

cd /d "%~dp0"

REM Kill old python processes
echo [1/3] Killing old python processes...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM pythonw.exe 2>nul
timeout /t 2 /nobreak >nul

REM Start Flask in background
echo [2/3] Starting Flask server on port 7860...
start "" pythonw server.py

REM Wait for server + auto-open browser
echo [3/3] Waiting for server...
set COUNT=0
:wait_loop
if !COUNT! geq 15 goto :open_browser
timeout /t 1 /nobreak >nul
set /a COUNT+=1
REM Try curl via PowerInvoke
powershell -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:7860/api/health' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" 2>nul
if !errorlevel! equ 0 goto :open_browser
goto :wait_loop

:open_browser
start "" http://localhost:7860

echo.
echo DONE! Browser should open http://localhost:7860
echo Close this window will NOT stop the server.
echo To stop, run stop.bat or kill python.exe
echo.
pause
