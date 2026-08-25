@echo off
cd /d "%~dp0"
title Markdown Screenshot Tool
echo Starting Markdown Screenshot Tool...
python run.py
if errorlevel 1 (
    echo.
    echo An error occurred while running the tool.
    pause
)
