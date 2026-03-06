@echo off
setlocal
cd /d "%~dp0"

powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_game.ps1" %*
set EXIT_CODE=%ERRORLEVEL%

echo.
if %EXIT_CODE% EQU 0 (
    echo Praxans finished successfully.
) else (
    echo Praxans exited with code %EXIT_CODE%.
)

pause
exit /b %EXIT_CODE%
