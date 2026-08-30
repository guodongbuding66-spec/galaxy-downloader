@echo off
setlocal
title Galaxy Local Engine Uninstaller
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Galaxy Local Engine uninstall step failed with exit code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
