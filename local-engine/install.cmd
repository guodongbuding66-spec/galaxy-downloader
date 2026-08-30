@echo off
setlocal
title Galaxy Local Engine Installer
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Galaxy Local Engine installation failed with exit code %EXITCODE%.
  pause
)
exit /b %EXITCODE%
