# Stock Ledger

> **Setting it up or giving a demo?** Start with [SETUP-GUIDE.md](SETUP-GUIDE.md).

Local stock ledger for raw material purchase, job work (labour out/in) and sales.
It runs on one factory PC, and phones on the same Wi-Fi open it in the browser.
All data stays in `data/stock.db` on that PC.

## Run it

1. Install Python 3.10+ from python.org. On Windows, tick **"Add Python to PATH"**.
2. Double-click **`start.bat`** (Windows) or run `./start.sh` (Mac/Linux).
   The first run installs dependencies.
3. On the PC, open **http://localhost:8000**.
4. On phones, open **http://&lt;PC-IP&gt;:8000**. Find the PC's IP with `ipconfig` (Windows), under IPv4 Address.
   - If Windows asks about the firewall, allow access on **private networks**.
   - On the phone, use "Add to Home screen" so it opens like an app.

Give the PC a fixed IP in the router so the phone link never changes.

## How it works

| Screen | What it does |
|---|---|
| Purchase In | Material + party (+ add new) + qty, bill no. Adds to stock. |
| Labour Out | Vendor + material + qty. Auto challan no. (LO-0001…). Removes from stock, opens a challan. |
| Labour In | Vendor → open challan → FG item/qty + scrap item/qty. Partial receipts allowed. Tick "complete" to close the challan; what's left is **burn** (auto-calculated, warns above 5%). |
| Sale Out | Item + party + qty, invoice no. Can't sell more than stock. |
| Opening Stock | Go-live balances. For material already lying with a vendor, use Labour Out with "Already with vendor" ticked. |
| Stock | Raw / Finished / Scrap / With Vendors (with days-out aging). Tap an item to see its ledger. |
| Ledger | Every entry with filters. Tap → detail → Edit / Delete. Every create/edit/delete is logged. |
| Masters | Items (name, HSN, type, unit), parties, vendors. Deactivate instead of delete. Backup download. |

Rules enforced by the server:

- Stock is never typed. It is always computed from entries, so it can't drift.
- Nothing can make stock negative: sales, labour out, edits and deletes are all checked.
- Labour In can't exceed what's pending on the challan.
- A Labour Out with receipts against it can't be deleted, and its item/vendor can't change.
- On a closed challan, only the closing Labour In can be deleted, which reopens the challan.
- Labour In is corrected by delete + re-enter, not edit.
- Deletes are soft (`deleted_at`), and the full history is in the `auditlog` table.

## Backups

- An automatic copy is made every day the app starts, in `data/backups/auto-YYYY-MM-DD.db`. The last 30 are kept.
- Masters → **Download backup** saves a copy anywhere you like.
- To restore: stop the app, replace `data/stock.db` with a backup file, start again.

## Project layout

```
main.py           FastAPI app: API, validations, backup, serves static/
models.py         SQLModel tables (item, party, vendor, entry, movement, labourlot, auditlog, user, loginsession)
seed.py           27 items + HSN from the client list, 4 vendors (runs on an empty DB only)
static/           index.html + app.js (Alpine.js) + app.css (prebuilt Tailwind) — no build needed to run
styles/input.css  Tailwind source. Rebuild after changing classes:
                  npx tailwindcss@3 -i styles/input.css -o static/app.css --minify
tests/            .venv/bin/pip install pytest httpx   then   .venv/bin/python -m pytest -q tests
```

## Logins

- **First run:** the app asks for the first editor's name and password, plus a **setup code** that is printed in the window where the app was started. Only someone at the server can see it, so nobody else on the network can grab the first account.
- **Masters → Users** (editors only): add people, set them as **Editor** (add/edit/delete, manage users) or **Viewer** (look only), reset passwords, or untick Active to stop someone logging in.
- On a phone or PC: tap your name, type your password. You stay logged in for 30 days.
- 5 wrong passwords lock that name for 5 minutes.
- Entry history shows who created, edited or deleted each entry.
- Locked out (no editor remembers their password)? On the PC, in the project folder, run
  `.venv\Scripts\python main.py reset-password "Name" newpassword` (Windows) or
  `.venv/bin/python main.py reset-password "Name" newpassword` (Mac/Linux).
  That person becomes an active editor with the new password.

## Reports

**Reports** in the menu. Everyone (editors and viewers) can open them.

| Report | What it shows |
|---|---|
| Item reconciliation | For a period, per item: opening + purchased + opening entries + job work in − job work out − sold = closing. Closing for a period ending today matches the Stock screen. |
| Vendor pending & aging | Open challans right now, and pending kg per vendor in 0–90 / 91–180 / 181–365 / over-1-year buckets (GST treats job work goods not back within 1 year as supplied). |
| Burn % | Challans closed in a period: sent, finished, scrap, burn and burn %, by vendor, by material and per challan. Above 5% is highlighted. |

- Pick a period with the chips (this month, last month, financial year, Apr–Sep, Oct–Mar) or the date boxes.
- **Export CSV** on any table opens straight in Excel.
- **Print / Save PDF** prints just the report (A4 landscape). Choose "Save as PDF" in the print dialog.

## Security notes

- Every API call needs a login; viewers can only read. The server enforces this, not just the screens.
- Passwords are stored as salted scrypt hashes. Login cookies are HttpOnly, and only a hash of each cookie is stored.
- 5 wrong passwords (or setup codes) lock that name for 5 minutes.
- Pages send security headers (no framing by other sites, strict content policy) and API responses aren't cached by the browser.
- CSV exports neutralise cells that start with `=`, `+`, `-` or `@`, so typed text can't run as an Excel formula.
- Run **one** server process only: the write lock and login lockout live in that process's memory.
- Over plain `http://` on the factory Wi-Fi, passwords travel unencrypted. Anything reachable from the internet must use HTTPS (the cookie is marked Secure automatically when it does).
