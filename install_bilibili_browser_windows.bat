@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run start_windows.bat once before installing the browser.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo Browser installation failed. Check network connectivity and retry.
) else (
  echo Browser installed. Return to CLab and start Bilibili import.
)
pause
