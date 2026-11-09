@echo off
title VBL Law Chambers - Starting Social Automation Suite
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service-manager.ps1" start
echo.
pause
