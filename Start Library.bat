@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start Library.ps1"
if errorlevel 1 (
  echo.
  echo The Offline Field Library did not start. See app\README.md for troubleshooting.
  pause
)
