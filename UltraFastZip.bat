@echo off
rem Launch Ultra Fast Zip GUI
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
    start "" .venv\Scripts\pythonw.exe app\main.py
) else (
    echo Virtual environment not found. Run setup.bat first.
    pause
)
