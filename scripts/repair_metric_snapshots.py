"""One-off repair: rebuild daily_* totals in metric snapshot files.

Historic bug: every dashboard render appended a shift entry to the day's
snapshot file and the day-level totals were SUMMED across all appends, so a
day that was rendered many times was counted many times (e.g. 2026-09-12
showed ৳18.6M / 11,035 orders instead of a realistic day's sales).

This script rebuilds each file's daily_revenue / daily_orders / daily_qty
from its last valid 'Today'-labelled shift entry (see
src.utils.metric_history.rebuild_daily_totals).

Dry-run by default: prints before → after for every file without writing.
Pass --apply to write changes; the original of every modified file is backed
up to --backup-dir (default: resources/metric_snapshots_backup).

Usage:
    python scripts/repair_metric_snapshots.py              # dry run
    python scripts/repair_metric_snapshots.py --apply      # write + backup
    python scripts/repair_metric_snapshots.py --apply --dir path/to/snapshots
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.constants import METRIC_SNAPSHOT_DIR
from src.utils.metric_history import rebuild_daily_totals

FIELDS = ("daily_revenue", "daily_orders", "daily_qty")


def repair_file(path: str) -> tuple[str, dict, dict]:
    """Repair one snapshot file. Returns (status, before, after)."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    before = {k: data.get(k) for k in FIELDS}
    if not rebuild_daily_totals(data):
        return "SKIPPED (no valid shift entries)", before, before

    after = {k: data.get(k) for k in FIELDS}
    if before == after:
        return "OK (already correct)", before, after

    if APPLY:
        backup_dir = os.path.join(
            os.path.dirname(path) or ".", os.path.basename(BACKUP_DIR)
        )
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(path, os.path.join(backup_dir, os.path.basename(path)))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return "REPAIRED", before, after
    return "WOULD REPAIR", before, after


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default: dry run)"
    )
    parser.add_argument(
        "--dir", default=METRIC_SNAPSHOT_DIR, help="Snapshot directory to repair"
    )
    parser.add_argument(
        "--backup-dir",
        default="metric_snapshots_backup",
        help="Backup folder name (created inside the snapshot dir's parent)",
    )
    args = parser.parse_args()

    global APPLY, BACKUP_DIR
    APPLY = args.apply
    BACKUP_DIR = args.backup_dir

    files = sorted(
        os.path.join(args.dir, f) for f in os.listdir(args.dir) if f.endswith(".json")
    )
    if not files:
        print(f"No snapshot files found in {args.dir}")
        return 0

    print(f"{'File':<18}{'Status':<32}{'Before (rev/orders/qty)':<28}After")
    repaired = 0
    for path in files:
        name = os.path.basename(path)
        try:
            status, before, after = repair_file(path)
        except Exception as exc:
            print(f"{name:<18}ERROR: {exc}")
            continue

        def fmt(d):
            return f"{d['daily_revenue']}/{d['daily_orders']}/{d['daily_qty']}"

        print(f"{name:<18}{status:<32}{fmt(before):<28}{fmt(after)}")
        if status in ("REPAIRED", "WOULD REPAIR"):
            repaired += 1

    mode = "APPLIED" if APPLY else "DRY RUN (no files written)"
    print(f"\n{mode}: {repaired} of {len(files)} file(s) need repair.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
