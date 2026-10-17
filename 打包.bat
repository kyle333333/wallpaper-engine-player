@echo off
rem ============================================================
rem  WE 壁纸播放器 - 一键打包（免安装绿色版）
rem  实际工作交给 packaging\build.ps1：
rem  中文路径全部由 PowerShell 的 Unicode API 处理，
rem  不经过 cmd 的代码页，避免文件名被打乱。
rem ============================================================
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\build.ps1"
if errorlevel 1 (
  echo.
  echo 打包失败，请看上面的提示。
)
echo.
pause
