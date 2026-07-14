@echo off
rem Ultra Fast Zip environment setup: create venv + install dependencies
cd /d "%~dp0"

if not exist .venv (
    echo [1/2] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv. Check that Python 3.11+ is installed.
        exit /b 1
    )
) else (
    echo [1/2] Using existing virtual environment ^(.venv^)
)

echo [2/2] Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    exit /b 1
)

echo.
echo Done! How to run:
echo   GUI : UltraFastZip.bat
echo   CLI : ufz.bat pack ^<folder^> / ufz.bat unpack ^<file.ufz^> / ufz.bat inspect ^<file.ufz^>
