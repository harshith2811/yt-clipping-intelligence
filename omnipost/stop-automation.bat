@echo off
title VBL Law Chambers - Stopping Social Automation Suite
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-manager.ps1" stop
echo.
pause
