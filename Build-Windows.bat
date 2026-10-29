@echo off
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher not found. Trying to install Python 3.12 with Winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo Install Python 3.12 from https://www.python.org/downloads/windows/ and retry.
        exit /b 1
    )
    winget install --exact --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    if errorlevel 1 exit /b 1
    where py >nul 2>&1
    if errorlevel 1 (
        echo Python was installed. Close this window, reopen it, and run again.
        pause
        exit /b 1
    )
)
py -3 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements-streaming.txt pyinstaller==6.16.0
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --onedir --windowed --collect-all aiortc --collect-all av --collect-all dxcam --collect-all soundcard --collect-all windows_capture --name PulsePlay launch.pyw
if errorlevel 1 exit /b 1
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo Inno Setup 6 was not found. Trying Winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo Install Inno Setup 6 from https://jrsoftware.org/isdl.php and retry.
        exit /b 1
    )
    winget install --exact --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements
    if errorlevel 1 exit /b 1
    set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC%" (
        echo Inno Setup was installed. Close this window, reopen it, and run again.
        pause
        exit /b 1
    )
)
"%ISCC%" installer.iss
if errorlevel 1 exit /b 1
echo Built: dist\PulsePlay-Setup.exe
pause
