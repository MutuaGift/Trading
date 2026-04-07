@echo off
:: ─────────────────────────────────────────────────────────────────────────────
:: start.bat  –  Single-command launcher for the AI trading bot stack on Windows.
::
:: Starts (via watchdog.py):
::   1. real_bot.py   (AI trading loop — connects to MT5 natively)
::   2. dashboard.py  (Streamlit UI  →  http://localhost:8501)
::
:: MetaTrader5 is launched automatically by the bot via mt5.initialize().
:: Make sure terminal64.exe is installed at:
::   C:\Program Files\MetaTrader 5\terminal64.exe
::
:: Flags:
::   --force   Kill any running instance and restart fresh.
:: ─────────────────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

:: Move to the directory containing this script
cd /d "%~dp0"

:: ── Handle --force flag ───────────────────────────────────────────────────────
set FORCE=0
for %%A in (%*) do (
    if /I "%%A"=="--force" set FORCE=1
)

if "%FORCE%"=="1" (
    echo [*] --force: stopping any running trading stack...
    taskkill /F /FI "WINDOWTITLE eq TradingBot*" >nul 2>&1
    :: Kill by PID from lock file if present
    set LOCK=%TEMP%\trading_watchdog.lock
    if exist "!LOCK!" (
        set /p OLD_PID=<"!LOCK!"
        if defined OLD_PID (
            taskkill /F /PID !OLD_PID! >nul 2>&1
        )
        del "!LOCK!" >nul 2>&1
    )
    :: Give processes time to exit
    timeout /T 3 /NOBREAK >nul
    echo [+] Existing stack stopped.
)

:: ── Pre-flight checks ─────────────────────────────────────────────────────────
echo.
echo   AI Trading Bot - Windows Launcher
echo ─────────────────────────────────────

set ERRORS=0

:: Check Python is available
where python >nul 2>&1
if errorlevel 1 (
    echo [!] ERROR: python not found in PATH.
    echo     Install Python 3.10+ from https://python.org
    set ERRORS=1
)

:: Check/create virtual environment
if not exist "venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [!] ERROR: Failed to create venv.
        set ERRORS=1
        goto :check_errors
    )
    echo [+] Virtual environment created.
    echo [*] Installing dependencies...
    venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo [!] ERROR: pip install failed.
        set ERRORS=1
        goto :check_errors
    )
    echo [+] Dependencies installed.
)

:: Check required files
if not exist "watchdog.py" (
    echo [!] ERROR: watchdog.py not found.
    set ERRORS=1
)
if not exist "real_bot.py" (
    echo [!] ERROR: real_bot.py not found.
    set ERRORS=1
)

:: Check MetaTrader5 is installed
venv\Scripts\python -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
    echo [!] WARNING: MetaTrader5 package not installed.
    echo     Installing now...
    venv\Scripts\pip install MetaTrader5
)

:: Check MT5 terminal exists
if not exist "C:\Program Files\MetaTrader 5\terminal64.exe" (
    echo [!] WARNING: MetaTrader 5 not found at default path.
    echo     Install MT5 from your broker or https://www.metatrader5.com
)

:: Check at least one model exists
set MODEL_COUNT=0
for %%F in (*_model.pkl) do set /A MODEL_COUNT+=1
if %MODEL_COUNT%==0 (
    echo [!] WARNING: No *_model.pkl files found.
    echo     Run train_model.py before starting the bot.
)

:check_errors
if %ERRORS%==1 (
    echo.
    echo [!] Aborting due to errors above.
    pause
    exit /B 1
)

:: ── Create log directory ──────────────────────────────────────────────────────
if not exist "logs" mkdir logs

:: ── Summary ───────────────────────────────────────────────────────────────────
echo.
echo   Components managed by watchdog (auto-restarted on crash):
echo     1  real_bot.py    (AI trading loop)
echo     2  dashboard.py   (Streamlit UI)
echo.
echo   MetaTrader5  -^>  launched automatically by the bot
echo   Dashboard    -^>  http://localhost:8501
echo   Logs         -^>  %~dp0logs\
echo.
echo   Press Ctrl-C to stop everything cleanly.
echo ─────────────────────────────────────
echo.

:: ── Launch the Python watchdog ────────────────────────────────────────────────
venv\Scripts\python watchdog.py

endlocal
