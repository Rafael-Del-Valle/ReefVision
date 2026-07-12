@echo off
setlocal
cd /d "%~dp0"
title ReefVision Prerequisite Check
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\check-prerequisites.ps1"
pause
