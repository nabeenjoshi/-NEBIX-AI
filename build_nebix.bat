@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
set "DISTROOT=%ROOT%dist\NEBIX-Portable"
set "WORKROOT=%ROOT%build\NEBIX-Portable"

if not exist "%PYTHON%" (
  echo ERROR: Build Python environment not found: "%PYTHON%"
  echo Create the project build environment and install requirements.txt first.
  exit /b 1
)

if exist "%DISTROOT%" rmdir /s /q "%DISTROOT%"
if exist "%WORKROOT%" rmdir /s /q "%WORKROOT%"
if errorlevel 1 (
  echo ERROR: Could not clear the prior NEBIX release build.
  exit /b 1
)

pushd "%ROOT%"
"%PYTHON%" -m PyInstaller --noconfirm --clean --distpath "%ROOT%dist" --workpath "%WORKROOT%" "%ROOT%NEBIX.spec"
set "BUILD_RESULT=%ERRORLEVEL%"
popd

if not "%BUILD_RESULT%"=="0" (
  echo ERROR: PyInstaller failed with exit code %BUILD_RESULT%.
  exit /b %BUILD_RESULT%
)

if not exist "%DISTROOT%\NEBIX.exe" (
  echo ERROR: Build reported success but NEBIX.exe is missing.
  exit /b 1
)

echo.
echo NEBIX standalone build created:
echo "%DISTROOT%\NEBIX.exe"
echo Copy the complete NEBIX folder when distributing the application.

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
  "%ISCC%" "%ROOT%installer\NEBIX.iss"
  if errorlevel 1 (
    echo ERROR: NEBIX installer compilation failed.
    exit /b 1
  )
  echo Installer created at "%ROOT%dist\installer\NEBIX-Setup.exe"
) else (
  echo NOTE: Inno Setup 6 was not found; the portable application is built,
  echo but installer\NEBIX.iss could not be compiled on this machine.
)
exit /b 0
