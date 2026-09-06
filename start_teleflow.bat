@echo off
title TeleFlow - Telegram Media Suite
color 0b
echo =======================================================
echo          TELEFLOW - HIGH PERFORMANCE SUITE
echo =======================================================
echo.

:: 1. Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your system PATH!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo IMPORTANT: Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b
)

:: 2. Check or create virtual environment
if not exist "venv\" (
    echo [*] First-time setup: Creating Python virtual environment (venv)...
    python -m venv venv
)

:: 3. Activate virtual environment
call venv\Scripts\activate.bat

:: 4. Check if dependencies are installed
python -c "import fastapi, telethon" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Installing required packages (this may take a minute on first run)...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
)

:: 5. Check if .env exists
if not exist ".env" (
    echo [*] Creating .env file from .env.example...
    copy .env.example .env >nul
    echo.
    echo =======================================================
    echo [ACTION REQUIRED] A new .env configuration file was created!
    echo Notepad will now open. Please paste your TG_API_ID,
    echo TG_API_HASH, and JWT_SECRET, save the file, and close it.
    echo =======================================================
    echo.
    notepad .env
    pause
)

:: 6. Launch TeleFlow
echo.
echo =======================================================
echo [*] Starting TeleFlow server on http://localhost:8000
echo [*] Press Ctrl+C in this window anytime to stop the server.
echo =======================================================
echo.
start http://localhost:8000
python app.py

pause
