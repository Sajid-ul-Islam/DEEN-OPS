@echo off
REM ====================================================================
REM Pathao Bulk Order Converter Launcher
REM Double-click to open GUI, or drag and drop an Excel file onto this .bat
REM ====================================================================
title Pathao Bulk Order Converter

set SCRIPT_DIR=%~dp0

REM Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not found in your system PATH.
    echo Please install Python 3.8+ from https://www.python.org/ or the Microsoft Store.
    echo.
    pause
    exit /b 1
)

REM If a file was dragged and dropped onto this batch file
if "%~1" NEQ "" (
    echo [INFO] Converting dropped file: "%~1"
    python "%SCRIPT_DIR%convert_to_pathao.py" --input "%~1"
    if %ERRORLEVEL% EQU 0 (
        echo.
        echo [SUCCESS] Conversion completed!
    ) else (
        echo.
        echo [ERROR] Conversion failed.
    )
    echo.
    pause
    exit /b %ERRORLEVEL%
)

REM Otherwise launch the GUI
echo [INFO] Starting Pathao Bulk Converter GUI...
python "%SCRIPT_DIR%convert_to_pathao.py" --gui
