@echo off
cd /d "%~dp0"
title Markdown Screenshot Tool

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Please install Python.
    echo.
    pause
    exit /b 1
)

python run.py
if errorlevel 1 (
    echo.
    echo [ERROR] Program exited with an error.
)

echo.
pause
