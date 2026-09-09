@echo off
chcp 65001 >nul
title Baomi Agent - 停止
echo 正在停止所有 Python 进程...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM pythonw.exe 2>nul
echo ✅ 已停止
pause
