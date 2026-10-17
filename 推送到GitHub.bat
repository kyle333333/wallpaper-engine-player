@echo off
rem ============================================================
rem  Push this repo to GitHub
rem  All Chinese text / logic lives in packaging\push.ps1 so it
rem  never passes through cmd's code page.
rem ============================================================
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\push.ps1"
