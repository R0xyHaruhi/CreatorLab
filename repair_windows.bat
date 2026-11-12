@echo off
call "%~dp0start_windows.bat" --repair --setup-only
if errorlevel 1 exit /b 1
pause
