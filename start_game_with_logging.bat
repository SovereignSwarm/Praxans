@echo off
setlocal
cd /d "%~dp0"

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_game.ps1" --verbose-console --log-level DEBUG %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% EQU 0 (
    echo Verbose Thronglets session complete.
) else (
    echo Verbose Thronglets session exited with code %EXIT_CODE%.
)

pause
exit /b %EXIT_CODE%
