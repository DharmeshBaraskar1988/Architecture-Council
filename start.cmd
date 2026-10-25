@echo off
rem Starts the viewer and council room (http://localhost:3000) in its own window and opens the browser.
rem Close that window, or press Ctrl+C in it, to stop the viewer.
if not exist "%~dp0frontend\node_modules" (
    echo The frontend is not installed yet. Run: setup
    exit /b 1
)
start "Council viewer" /D "%~dp0frontend" cmd /k npm run dev
timeout /t 8 /nobreak >nul
start "" http://localhost:3000
