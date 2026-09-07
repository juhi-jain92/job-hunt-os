"""
prune_ledger.py — Deletes ledger rows older than a week.

The referral window is 48 hours and the ledger is machinery, not a record:
a role posted more than a week ago is noise on every read. Rows Juhi marked
applied / interviewing / rejected / skipped are kept regardless of age — those
are hers. The Referrals and Networking tabs are untouched.

Rebuilds the tab in one write (read → filter → clear → write) instead of
deleting rows one by one.

Usage:
    python3 prune_ledger.py --dry-run
    python3 prune_ledger.py               keep the last 7 days
    python3 prune_ledger.py --days 14
"""

import sys
from datetime import datetime, timedelta

import sheets

KEEP_STATUSES = sheets.JOB_USER_STATUSES
DRY_RUN = "--dry-run" in sys.argv
DAYS = 7
if "--days" in sys.argv:
    try:
        DAYS = int(sys.argv[sys.argv.index("--days") + 1])
    except (IndexError, ValueError):
        pass


def posted_date(value: str):
    v = (value or "").strip()[:10]
    try:
        return datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        return None


def main():
    ws = sheets.open_or_create_sheet()
    rows = sheets.get_all_rows_with_numbers(ws)
    cutoff = datetime.now() - timedelta(days=DAYS)

    keep, drop = [], []
    for r in rows:
        status = (r.get("status", "") or "").strip().lower()
        posted = posted_date(r.get("posted_at", ""))
        # Unknown date: keep — never delete on a guess.
        if status in KEEP_STATUSES or posted is None or posted >= cutoff:
            keep.append(r)
        else:
            drop.append(r)

    print(f"  {len(rows)} rows · keep {len(keep)} · delete {len(drop)} "
          f"(posted before {cutoff:%Y-%m-%d}, not in {sorted(KEEP_STATUSES)})")
    if not drop:
        return
    if DRY_RUN:
        print("  --dry-run — nothing deleted.")
        return

    values = [sheets.COLUMNS] + [[r.get(c, "") for c in sheets.COLUMNS] for r in keep]

    # clear() then update() is not atomic. If the update fails the ledger is a
    # bare header, so park the full pre-prune ledger in a backup tab first and
    # refuse to proceed unless that write landed.
    full = [sheets.COLUMNS] + [[r.get(c, "") for c in sheets.COLUMNS] for r in rows]
    bk = sheets.open_or_create_tab("ledger_backup", sheets.COLUMNS, rows=len(full) + 10)
    bk.clear()
    bk.update(values=full, range_name="A1", value_input_option="RAW")
    if len(values) < 1 or len(values[0]) != len(sheets.COLUMNS):
        sys.exit("  [FATAL] refusing to rebuild: computed ledger has the wrong shape.")

    ws.clear()
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    print(f"  Ledger rebuilt: {len(keep)} rows (pre-prune copy in 'ledger_backup').")


if __name__ == "__main__":
    main()
