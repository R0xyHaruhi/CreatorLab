@echo off
call "%~dp0start_windows.bat" --setup-only
if errorlevel 1 exit /b 1
pause
