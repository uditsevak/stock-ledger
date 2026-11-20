"""Off-site backup copy. Run:  python -m pytest -q tests"""
from conftest import OWNER, login

import main


def test_offsite_copy(tmp_path, monkeypatch):
    c = login(*OWNER)
    drive = tmp_path / "My Drive"  # stands in for the Google Drive / OneDrive folder
    drive.mkdir()
    monkeypatch.setattr(main, "OFFSITE_DIR", str(drive / "Stock Ledger Backups"))
    for old in ("auto-2020-01-01.db", "auto-2020-01-02.db"):
        (drive / "Stock Ledger Backups").mkdir(exist_ok=True)
        (drive / "Stock Ledger Backups" / old).write_bytes(b"old")
    main.daily_auto_backup(keep=2)
    copies = sorted(p.name for p in (drive / "Stock Ledger Backups").iterdir())
    today = f"auto-{main.date.today().isoformat()}.db"
    assert copies == ["auto-2020-01-02.db", today]  # oldest pruned, no leftover .part file
    assert (drive / "Stock Ledger Backups" / today).read_bytes()[:15] == b"SQLite format 3"
    st = c.get("/api/backup/status").json()
    assert st["last_offsite"] == today[5:-3] and st["offsite_error"] == "" and st["last_local"] == today[5:-3]

    # Drive not installed (parent folder missing): reported, and no stray local folder made
    monkeypatch.setattr(main, "OFFSITE_DIR", str(tmp_path / "No Drive" / "Backups"))
    main.daily_auto_backup()
    st = c.get("/api/backup/status").json()
    assert st["offsite_error"] and st["last_offsite"] is None and not (tmp_path / "No Drive").exists()
    monkeypatch.setattr(main, "OFFSITE_DIR", "")
    main.daily_auto_backup()  # off-site not set up: fine, nothing to do
