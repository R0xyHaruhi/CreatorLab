@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
py -3.12 -c "import sys" >nul 2>&1
if errorlevel 1 goto :fallback
py -3.12 bootstrap.py %*
goto :done
:fallback
python -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo Install 64-bit Python 3.12 from https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
python bootstrap.py %*
:done
set "CLAB_RESULT=%errorlevel%"
if not "%CLAB_RESULT%"=="0" pause
exit /b %CLAB_RESULT%
