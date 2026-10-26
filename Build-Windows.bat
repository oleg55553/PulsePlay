@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install pyinstaller==6.16.0
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onefile --windowed --name PulsePlay app.py
if errorlevel 1 exit /b 1
echo Built: dist\PulsePlay.exe
pause
