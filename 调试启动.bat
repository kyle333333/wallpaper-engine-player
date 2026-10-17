@echo off
chcp 65001 >nul
title WE 壁纸播放器 - 调试模式
cd /d "%~dp0"

set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Launcher\py.exe"

if not defined PY (
  echo 没有找到 Python，请先安装 Python 3.8+ 并勾选 Add Python to PATH。
  pause
  exit /b 1
)

echo 启动 WE 壁纸播放器（关闭本窗口即退出程序）...
echo.
"%PY%" "%~dp0we_player.py" %*
echo.
echo 程序已退出。日志见 data\player.log
pause
