@echo off
setlocal
cd /d "%~dp0"
title ReefVision First-Time Setup
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1" -ProviderRequirementsFile "requirements\providers-windows-cu121-py312.txt"
if errorlevel 1 (
    echo.
    echo ReefVision setup did not complete. Read the message above for the exact fix.
    pause
    exit /b 1
)
echo.
echo ReefVision setup completed successfully.
pause
