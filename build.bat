@echo off
rem Build distributable executables with PyInstaller
rem Output: dist\UltraFastZip\UltraFastZip.exe (GUI), dist\ufz.exe (CLI)
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

.venv\Scripts\python.exe -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    .venv\Scripts\python.exe -m pip install pyinstaller -q
)

if not exist assets\icon.ico (
    echo Generating app icon...
    .venv\Scripts\python.exe scripts\make_icon.py
)

echo [1/2] Building GUI (UltraFastZip)...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --noconsole --name UltraFastZip --paths . --icon assets\icon.ico --add-data "assets;assets" app\main.py
if errorlevel 1 exit /b 1

echo [2/2] Building CLI (ufz)...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --console --name ufz --paths . --icon assets\icon.ico app\cli.py
if errorlevel 1 exit /b 1

echo.
echo Done!
echo   GUI : dist\UltraFastZip\UltraFastZip.exe
echo   CLI : dist\ufz.exe
