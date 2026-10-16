@echo off
title RAX Surgicals Outreach
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python is not installed.
  echo Download it from https://www.python.org/downloads/  and tick "Add python.exe to PATH" while installing.
  echo Then double-click this file again.
  echo.
  pause
  exit /b
)
%PY% start.py %*
pause
