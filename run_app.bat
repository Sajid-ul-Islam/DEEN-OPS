
@echo off
echo Starting Pathao Order Automation App...
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" -m streamlit run app.py
pause
