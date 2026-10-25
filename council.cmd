@echo off
rem The council command without activating the venv. From the council folder:
rem   council validate
rem   council run --prd data\samples\prds\s1_financial_briefing.md --review skip
if not exist "%~dp0backend\.venv\Scripts\council.exe" (
    echo The backend is not installed yet. Run: setup
    exit /b 1
)
"%~dp0backend\.venv\Scripts\council.exe" %*
