@echo off
setlocal
cd /d "%~dp0"

call "%~dp0start_game.bat" %*
exit /b %ERRORLEVEL%
