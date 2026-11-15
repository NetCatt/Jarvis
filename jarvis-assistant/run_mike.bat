@echo off
title Mike Ross - Voice Assistant
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo Mike Ross exited with an error. See above for details.
)
pause
