@echo off
rem Runs setup.ps1 even when PowerShell scripts are blocked (execution policy Restricted).
rem Usage: setup            or: setup -SkipFrontend   (same switches as setup.ps1)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
