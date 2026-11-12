@echo off
call "%~dp0start_windows.bat" --restore
if errorlevel 1 exit /b 1
pause
