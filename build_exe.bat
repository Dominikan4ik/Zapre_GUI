@echo off
cd /d "%~dp0"
where python >nul 2>nul || goto :nopy
python -m pip install -r requirements.txt pyinstaller || goto :err
python tools\make_icon.py
set ICON=
if exist "assets\icon.ico" set ICON=--icon assets\icon.ico
python -m PyInstaller --noconfirm --clean --onedir --windowed --uac-admin --noupx %ICON% --name ZapretManager --exclude-module tkinter --exclude-module unittest main.py || goto :err
if exist "zapret" xcopy /E /I /Y "zapret" "dist\ZapretManager\zapret" >nul
echo.
echo Done: dist\ZapretManager\ZapretManager.exe
pause
exit /b 0
:nopy
echo Python 3.10+ not found. Install it from python.org (tick "Add python to PATH").
pause
exit /b 1
:err
echo Build failed, see messages above.
pause
exit /b 1
