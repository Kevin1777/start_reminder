@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=.venv\Scripts\python.exe"
set "STATE_FILE=data\sent.json"

echo ========================================
echo   Football pre-match reminder - START
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.10+ was not found.
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [SETUP] Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo [SETUP] Installing/checking dependencies...
"%PYTHON_EXE%" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check your network connection.
    pause
    exit /b 1
)

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo.
    echo [CONFIG] .env was created. Fill in WECOM_WEBHOOK_URL and run this file again.
    notepad ".env"
    pause
    exit /b 1
)

echo [RUNNING] Started. Checking every minute; refreshing schedule hourly.
echo [RUNNING] Close this window to stop.
echo.

:loop
echo [%date% %time%] Checking schedule...
"%PYTHON_EXE%" five_league_reminder.py
if errorlevel 1 echo [%date% %time%] Check failed. Retrying in 1 minute.
timeout /t 60 /nobreak >nul
goto loop
