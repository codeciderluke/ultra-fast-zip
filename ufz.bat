@echo off
rem Ultra Fast Zip CLI wrapper: ufz pack <folder> / ufz unpack <file.ufz> / ufz inspect <file.ufz>
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe app\cli.py %*
) else (
    python app\cli.py %*
)
