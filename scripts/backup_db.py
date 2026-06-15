"""Nightly online backup of the live competition DB.

The whole tournament is ONE SQLite file on the home server; a disk hiccup or a bad
write would destroy six weeks of irreproducible competition data. This snapshots
worldcup.db into backups/ using the sqlite3 backup API — safe to run while the tick
is writing (it takes a consistent copy, never a torn one) — and prunes snapshots
older than KEEP_DAYS. Scheduled by deploy/wc-backup.timer; also fine to run by hand:

    uv run python scripts/backup_db.py
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB = Path("worldcup.db")  # resolved from cwd, like the orchestrator (run at repo root)
DEST_DIR = Path("backups")
KEEP_DAYS = 21


def main() -> None:
    """Create a timestamped SQLite backup and prune expired backup files."""
    if not DB.exists():
        sys.exit(f"{DB} not found — run from the repo root")
    DEST_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = DEST_DIR / f"worldcup-{stamp}.db"

    src = sqlite3.connect(DB)
    dst = sqlite3.connect(dest)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()

    cutoff = time.time() - KEEP_DAYS * 86400
    pruned = 0
    for f in DEST_DIR.glob("worldcup-*.db"):
        if f != dest and f.stat().st_mtime < cutoff:
            f.unlink()
            pruned += 1

    print(f"backup: {dest} ({dest.stat().st_size:,} bytes); pruned {pruned} old")


if __name__ == "__main__":
    main()
