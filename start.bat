@echo off
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting up...
  python -m venv .venv || (echo Python not found. Install it from python.org and tick "Add Python to PATH". & pause & exit /b)
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
echo.
echo Stock Ledger is running. Open http://localhost:8000
echo On phones: http://THIS-PC-IP:8000   (find IP with: ipconfig)
echo Keep this window open. Close it to stop the app.
echo.
.venv\Scripts\python main.py
pause
