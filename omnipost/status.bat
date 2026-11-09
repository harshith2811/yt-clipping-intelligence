@echo off
title VBL Law Chambers - Social Automation Suite Status
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-manager.ps1" status
echo.
pause
