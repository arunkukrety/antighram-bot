@echo off
REM =============================================================================
REM install.bat — Antighram Bot Desktop App Installer (Windows)
REM =============================================================================
REM Double-click to run, or execute from Command Prompt / PowerShell.
REM
REM What it does:
REM   1. Creates a Python virtual environment inside the project
REM   2. Installs all bot + GUI dependencies
REM   3. Prompts for Telegram credentials if .env is missing
REM   4. Creates a Desktop shortcut (pythonw — no console window)
REM   5. Creates a Start Menu entry
REM =============================================================================

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "VENV_DIR=%SCRIPT_DIR%\.venv"
set "DESKTOP=%USERPROFILE%\Desktop"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

echo.
echo  ============================================
echo     Antighram Bot Installer
echo  ============================================
echo.

REM ── Check Python ────────────────────────────────────────────────────────────
echo [1/6] Checking Python 3...
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python 3 not found. Download from https://python.org and re-run.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo       Found Python %%v

REM ── Virtual environment ──────────────────────────────────────────────────────
echo.
echo [2/6] Setting up virtual environment...
if not exist "%VENV_DIR%" (
    python -m venv "%VENV_DIR%"
    echo       Created .venv
) else (
    echo       .venv already exists — skipping
)

REM ── Install dependencies ─────────────────────────────────────────────────────
echo.
echo [3/6] Installing bot dependencies...
"%VENV_DIR%\Scripts\pip.exe" install --upgrade pip --quiet
"%VENV_DIR%\Scripts\pip.exe" install -r "%SCRIPT_DIR%\requirements.txt" --quiet
echo       Bot dependencies installed.

echo.
echo [4/6] Installing GUI dependencies...
"%VENV_DIR%\Scripts\pip.exe" install -r "%SCRIPT_DIR%\requirements-gui.txt" --quiet
echo       GUI dependencies installed.

REM ── Configure .env ──────────────────────────────────────────────────────────
echo.
echo [5/6] Configuring environment...
set "ENV_FILE=%SCRIPT_DIR%\.env"
if not exist "%ENV_FILE%" (
    echo  No .env file found. Let's configure it now.
    echo.
    set /p "BOT_TOKEN=  Telegram Bot Token (from @BotFather): "
    set /p "CHAT_IDS=  Allowed Chat IDs (comma-separated, blank to skip): "
    (
        echo TELEGRAM_BOT_TOKEN=!BOT_TOKEN!
        echo TELEGRAM_ALLOWED_CHAT_IDS=!CHAT_IDS!
        echo AGY_BIN=agy
        echo AGY_DEFAULT_WORKSPACE=%USERPROFILE%\agy-server-workspace
        echo AGY_PRINT_TIMEOUT=300
    ) > "%ENV_FILE%"
    echo       .env created.
) else (
    echo       .env already exists — skipping.
)

REM ── Shortcuts ────────────────────────────────────────────────────────────────
echo.
echo [6/6] Creating shortcuts...

set "PYTHONW=%VENV_DIR%\Scripts\pythonw.exe"
set "GUI_SCRIPT=%SCRIPT_DIR%\gui_app.py"

REM Use PowerShell to create a proper .lnk shortcut
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%DESKTOP%\Antighram Bot.lnk'); ^
   $s.TargetPath = '%PYTHONW%'; ^
   $s.Arguments = '\"%GUI_SCRIPT%\"'; ^
   $s.WorkingDirectory = '%SCRIPT_DIR%'; ^
   $s.Description = 'Antighram Bot Control Center'; ^
   $s.IconLocation = '%PYTHONW%'; ^
   $s.Save()"

if exist "%DESKTOP%\Antighram Bot.lnk" (
    echo       Desktop shortcut created.
) else (
    echo       Warning: Desktop shortcut could not be created.
)

REM Start Menu shortcut
if not exist "%STARTMENU%\Antighram Bot" mkdir "%STARTMENU%\Antighram Bot"
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%STARTMENU%\Antighram Bot\Antighram Bot.lnk'); ^
   $s.TargetPath = '%PYTHONW%'; ^
   $s.Arguments = '\"%GUI_SCRIPT%\"'; ^
   $s.WorkingDirectory = '%SCRIPT_DIR%'; ^
   $s.Description = 'Antighram Bot Control Center'; ^
   $s.Save()"

echo       Start Menu entry created.

REM ── Done ─────────────────────────────────────────────────────────────────────
echo.
echo  ============================================
echo     Installation complete!
echo  ============================================
echo.
echo   Launch the bot control center:
echo     - Double-click "Antighram Bot" on your Desktop
echo     - Or run: python gui_app.py  (from project folder)
echo.
echo   The app will minimize to the system tray.
echo   Left-click the tray icon to open the control panel.
echo.

pause
endlocal
