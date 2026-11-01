@echo off
cd /d "%~dp0"
where python >nul 2>nul || goto :nopy
python -c "import PySide6" >nul 2>nul || goto :install
:start
start "" pythonw main.py
exit /b 0
:install
echo Installing PySide6, please wait...
python -m pip install -r requirements.txt || goto :err
goto :start
:nopy
echo Python 3.10+ not found. Install it from python.org (tick "Add python to PATH").
pause
exit /b 1
:err
echo Install failed, see messages above.
pause
exit /b 1
