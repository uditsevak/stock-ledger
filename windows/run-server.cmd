@echo off
rem Started by the "Stock Ledger" scheduled task (see service.ps1). Keeps the app running:
rem if it ever stops, it is started again after 10 seconds.
cd /d "%~dp0.."
:loop
".venv\Scripts\python.exe" main.py
echo %date% %time% Stock Ledger stopped (exit code %errorlevel%), starting again in 10 seconds>> "data\logs\restarts.log"
rem ping is used as a sleep: timeout does not work without a console window
ping -n 11 127.0.0.1 > nul
goto loop
