@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0dist\PulsePlay.exe" (
    start "" "%~dp0dist\PulsePlay.exe"
    exit /b 0
)
if exist "%~dp0PulsePlay.exe" (
    start "" "%~dp0PulsePlay.exe"
    exit /b 0
)
py -3 -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import subprocess,sys,pathlib; p=pathlib.Path(sys.executable); w=p.with_name('pythonw.exe'); subprocess.Popen([str(w if w.exists() else p), 'launch.pyw'])"
    exit /b 0
)
python -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
    python -c "import subprocess,sys,pathlib; p=pathlib.Path(sys.executable); w=p.with_name('pythonw.exe'); subprocess.Popen([str(w if w.exists() else p), 'launch.pyw'])"
    exit /b 0
)
echo PulsePlay needs Python 3 with Tcl/Tk support.
echo Install Python from https://www.python.org/downloads/windows/
echo Enable Python Launcher and Tcl/Tk during installation.
echo Then double-click START.cmd again.
pause
exit /b 1
