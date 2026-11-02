# Stock Ledger: notes for Claude Code

Local stock ledger for a copper/brass manufacturer. FastAPI + SQLite (SQLModel) + Alpine.js + prebuilt Tailwind. No build step to run.

- Stock is derived: SUM(movement.qty) over entries where deleted_at IS NULL. Never store stock.
- Every write goes through WRITE_LOCK, then `ensure_stock()` / `ensure_lot()` after flush. Raise HTTPException before commit to reject.
- Labour flow: Labour Out creates a LabourLot (challan). Labour In entries reference lot_id, with movements RECV (metal back) and SCRAP. Closing sets burn_qty = pending at close.
- Materials: entries send `spec: {material_id, shape_id, grade_id, size}`; `resolve_item()` finds or makes the stock line (`Item`). "Type" on screen is the `Shape` table. Grades belong to a material. Scrap materials (`is_scrap`) ignore type/grade/size. Size matches on `size_key` (lower case, no spaces); keep `clean_size()` and `sizeKey()` in app.js the same. Item.type is RAW/SCRAP, derived from the material. HSN is typed per entry (`Entry.hsn`), not stored on items.
- Renaming a material/type/grade must call `refresh_item_names()` (`_commit_master` does).
- index.html has one Material/Type/Grade/Size block (`#spec-tpl`); `stampSpecBlocks()` copies it into each `<div data-spec="spec|recv">` before Alpine starts.
- Users are factory staff on phones: big tap targets, pickers over typing, plain-English errors.
- After changing classes in static/*, rebuild CSS: `npx tailwindcss@3 -i styles/input.css -o static/app.css --minify`
- Tests: `.venv/bin/python -m pytest -q tests` (needs pytest + httpx; uses a temp STOCK_DATA_DIR shared by all test files, so assert on your own rows, not global counts).
- Single process only (WRITE_LOCK, login lockout and SETUP_CODE are in memory). Deps are pinned in requirements.txt.

- Auth: every /api route except /api/auth/* needs a login (global `require_login` dependency). Viewers get GET only; /api/backup and /api/users are editor-only. `audit()` records the user via the `CURRENT_USER` contextvar. Frontend hides editor controls with `canEdit`, but the server is the real check.
- Schema changes to existing tables need a manual `ALTER TABLE` in `init_db()` (create_all only makes new tables).

- Reports: each `/api/reports/*` returns `{tables: [{key, title, cols: [[field, label, kind]], rows, total?}]}`. The frontend renders and CSV-exports any table generically, so a new report needs only a backend function plus an entry in `REPORTS` (app.js).
