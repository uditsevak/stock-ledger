@echo off
rem Double-click to stop the Stock Ledger background service. Windows will ask for admin permission.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0service.ps1" stop
pause
