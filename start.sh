#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
echo "Stock Ledger running: http://localhost:8000  (phones: http://<this-pc-ip>:8000)"
.venv/bin/python main.py
