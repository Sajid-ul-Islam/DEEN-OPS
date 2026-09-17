@echo off
setlocal

echo ========================================================
echo   DEEN-OPS :: SIP Item-Wise Outlet Processor
echo ========================================================

set SCRIPT_DIR=%~dp0
set VENV_PYTHON=%SCRIPT_DIR%..\..\.venv\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    set VENV_PYTHON=python
)

if "%~1"=="" (
    echo Usage: Drag and drop an Excel/CSV order file onto this batch file
    echo        or specify the file path as an argument.
    echo.
    set /p INPUT_FILE="Enter path to order file: "
) else (
    set INPUT_FILE=%~1
)

if not exist "%INPUT_FILE%" (
    echo Error: File not found: %INPUT_FILE%
    pause
    exit /b 1
)

"%VENV_PYTHON%" "%SCRIPT_DIR%process_sip_outlets.py" "%INPUT_FILE%"

echo.
pause
