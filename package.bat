@echo off
rem Assemble distribution folder + zip from build outputs
rem Requires: build.bat has been run (dist\UltraFastZip, dist\ufz.exe)
cd /d "%~dp0"
setlocal

set VER=1.0
set REL=release\UltraFastZip_v%VER%

if not exist dist\UltraFastZip\UltraFastZip.exe (
    echo Build output not found. Run build.bat first.
    exit /b 1
)

if exist "%REL%" rmdir /s /q "%REL%"
mkdir "%REL%"

echo [1/4] Copying GUI...
xcopy /e /i /q dist\UltraFastZip "%REL%\UltraFastZip" >nul

echo [2/4] Copying CLI...
copy /y dist\ufz.exe "%REL%\" >nul

echo [3/4] Copying README, license, and manual...
copy /y README_DIST.txt "%REL%\README.txt" >nul
copy /y LICENSE "%REL%\" >nul
copy /y NOTICE.md "%REL%\" >nul
if exist docs\UltraFastZip_UserManual.pdf copy /y docs\UltraFastZip_UserManual.pdf "%REL%\" >nul

echo [4/4] Creating zip...
if exist "release\UltraFastZip_v%VER%.zip" del "release\UltraFastZip_v%VER%.zip"
powershell -NoProfile -Command "Compress-Archive -Path '%REL%\*' -DestinationPath 'release\UltraFastZip_v%VER%.zip'"

echo.
echo Done!
echo   Folder : %REL%
echo   Zip    : release\UltraFastZip_v%VER%.zip
endlocal
