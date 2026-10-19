# Stock Ledger: notes for Claude Code

Local stock ledger for a copper/brass manufacturer. FastAPI + SQLite (SQLModel) + Alpine.js + prebuilt Tailwind. No build step to run.

- Stock is derived: SUM(movement.qty) over entries where deleted_at IS NULL. Never store stock.
- Every write goes through WRITE_LOCK, then `ensure_stock()` / `ensure_lot()` after flush. Raise HTTPException before commit to reject.
- Labour flow: Labour Out creates a LabourLot (challan). Labour In entries reference lot_id. Closing sets burn_qty = pending at close.
- Item types RAW/FG/SCRAP only group/sort the pickers. They don't restrict anything.
- Users are factory staff on phones: big tap targets, pickers over typing, plain-English errors.
- After changing classes in static/*, rebuild CSS: `npx tailwindcss@3 -i styles/input.css -o static/app.css --minify`
- Tests: `.venv/bin/python -m pytest -q tests` (needs pytest + httpx; uses a temp STOCK_DATA_DIR shared by all test files, so assert on your own rows, not global counts).
- Single process only (WRITE_LOCK, login lockout and SETUP_CODE are in memory). Deps are pinned in requirements.txt.

- Auth: every /api route except /api/auth/* needs a login (global `require_login` dependency). Viewers get GET only; /api/backup and /api/users are editor-only. `audit()` records the user via the `CURRENT_USER` contextvar. Frontend hides editor controls with `canEdit`, but the server is the real check.
- Schema changes to existing tables need a manual `ALTER TABLE` in `init_db()` (create_all only makes new tables).

- Reports: each `/api/reports/*` returns `{tables: [{key, title, cols: [[field, label, kind]], rows, total?}]}`. The frontend renders and CSV-exports any table generically, so a new report needs only a backend function plus an entry in `REPORTS` (app.js).
