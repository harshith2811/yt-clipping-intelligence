@echo off
title VBL Law Chambers - Stopping Social Automation Suite
echo Stopping VBL Law Chambers Automation Suite gracefully...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-manager.ps1" stop
echo.
pause
