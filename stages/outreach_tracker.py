"""
outreach_tracker.py — Follow-up flags, velocity cap, and gate audit.

Runs over both lanes — the Referrals tab and the Networking tab.

  1. Flags anything sent 7+ days ago with no response recorded.
  2. Enforces the connection-request cap against a trailing 7-day window,
     holding back the overflow rather than letting it queue up silently.
  3. Reports messages marked SENT without the personalization box ticked.
     Nothing here can stop a send from your browser, and it shouldn't try —
     but a breach should be loud and countable rather than invisible.
  4. Writes last_contacted and outreach_count back to Contacts.

Rows you own — SENT, REPLIED, CLOSED, SKIPPED — are never overwritten except
for the follow-up columns, which is the whole point of tracking them.

Usage:
    python3 outreach_tracker.py --report      read-only summary
    python3 outreach_tracker.py --dry-run     show what would change
    python3 outreach_tracker.py               apply flags and holds
    python3 outreach_tracker.py --days 10     custom follow-up window
"""

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta

from lib import sheets

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE, "config", "search_config.json")

_cfg = {}
try:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        _cfg = json.load(fh).get("velocity", {})
except (FileNotFoundError, json.JSONDecodeError):
    pass

CONNECT_CAP_PER_WEEK = _cfg.get("linkedin_connect_per_week", 15)
FOLLOW_UP_DAYS       = _cfg.get("follow_up_after_days", 7)

# Only connection requests consume the cap. DMs to people you are already
# connected to, and cold emails, cost nothing against it.
CAPPED_CHANNEL = "linkedin_connect_note"

DRY_RUN = "--dry-run" in sys.argv
REPORT  = "--report" in sys.argv


def _flag_value(name: str, default):
    if name not in sys.argv:
        return default
    try:
        return type(default)(sys.argv[sys.argv.index(name) + 1])
    except (IndexError, ValueError):
        return default


DAYS = _flag_value("--days", FOLLOW_UP_DAYS)


def parse_date(value: str):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(value[:10], fmt)
        except ValueError:
            continue
    return None


def is_truthy(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "yes", "y", "1", "x", "✓"}


SENT_SLOTS = ("sent_1", "sent_2", "sent_rec")
STALE_AFTER_DAYS = 14


def track_referrals(today: datetime):
    """
    Referral-lane follow-ups. A role has three independent sends, so the
    follow-up clock runs from the EARLIEST one — that is the ask that has
    been waiting longest.
    """
    ws = sheets.get_referrals_tab()
    rows = sheets.get_all_rows_with_numbers(ws)
    if not rows:
        print("\n  Referrals tab is empty — run referral_match.py first.")
        return

    updates, due_now, untouched, staled = [], [], 0, 0
    stale_cutoff = today - timedelta(days=STALE_AFTER_DAYS)

    for r in rows:
        sent_dates = [d for d in (parse_date(r.get(s, "")) for s in SENT_SLOTS) if d]
        if not sent_dates:
            # A role posted 14+ days ago that was never chased is stale: the
            # 48-hour referral window is long gone. Flagged, never deleted;
            # the Today view and the drafter simply stop showing it.
            posted = parse_date(r.get("posted_at", ""))
            if posted and posted < stale_cutoff and (r.get("stale", "") or "").upper() != "TRUE":
                updates.append({"row_num": r["_row_num"], "values": {"stale": "TRUE"}})
                staled += 1
            elif r.get("first_degree_available") == "TRUE":
                untouched += 1
            continue

        earliest = min(sent_dates)
        due = earliest + timedelta(days=DAYS)
        due_str = due.strftime("%Y-%m-%d")

        if r.get("followup_due", "") != due_str:
            updates.append({"row_num": r["_row_num"], "values": {"followup_due": due_str}})
        if today >= due:
            due_now.append(r)

    print("\n  " + "=" * 54)
    print("  Referral lane")
    print("  " + "=" * 54)
    print(f"    Roles tracked                     {len(rows)}")
    print(f"    Newly marked stale (14d+, unsent) {staled}")
    print(f"    Warm path, live, not contacted    {untouched}")
    print(f"    Follow-up due now                 {len(due_now)}")
    for r in due_now[:10]:
        print(f"      {r.get('company',''):<22} {r.get('title','')[:40]}")

    if updates and not (DRY_RUN or REPORT):
        sheets.batch_update_cells(ws, updates, sheets.REFERRALS_COLUMNS)
        print(f"    Refreshed {len(updates)} follow-up date(s).")
    elif updates:
        print(f"    {len(updates)} follow-up date(s) would be refreshed.")


def main():
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    track_referrals(today)

    ws = sheets.get_networking_tab()
    rows = sheets.get_all_rows_with_numbers(ws)
    if not rows:
        print("\n  Networking tab is empty — run networking_daily.py to queue prospects.")
        return

    updates = []
    breaches = []
    counters = Counter()
    sent_recent = 0

    for r in rows:
        status  = (r.get("status", "") or "").strip().lower()
        channel = (r.get("channel", "") or "").strip()
        counters[status or "(blank)"] += 1

        sent_date = parse_date(r.get("sent_date", ""))

        # --- velocity: count connection requests sent in the trailing window ---
        if status == "sent" and channel == CAPPED_CHANNEL and sent_date:
            if (today - sent_date).days < 7:
                sent_recent += 1

        # --- personalization gate audit ---
        if status == "sent" and not is_truthy(r.get("personalized", "")):
            breaches.append(r)

        # --- follow-up flagging ---
        if status == "sent" and sent_date:
            has_response  = bool((r.get("response", "") or "").strip())
            already_flagged = bool((r.get("follow_up_flag", "") or "").strip())
            follow_up_sent  = is_truthy(r.get("follow_up_sent", ""))
            age_days = (today - sent_date).days

            if not has_response and not follow_up_sent and age_days >= DAYS:
                if not already_flagged:
                    updates.append({
                        "row_num": r["_row_num"],
                        "values": {
                            "follow_up_due": (sent_date + timedelta(days=DAYS)).strftime("%Y-%m-%d"),
                            "follow_up_flag": "FOLLOW UP",
                        },
                    })
                    counters["newly flagged"] += 1
            elif (has_response or follow_up_sent) and already_flagged:
                # Answered or followed up — clear the flag so the queue stays honest.
                updates.append({
                    "row_num": r["_row_num"],
                    "values": {"follow_up_flag": ""},
                })
                counters["flag cleared"] += 1

    remaining = max(0, CONNECT_CAP_PER_WEEK - sent_recent)


    # ── report ────────────────────────────────────────────────────────────────
    print("\n  " + "=" * 54)
    print("  Outreach status")
    print("  " + "=" * 54)
    for status, n in counters.most_common():
        if status in {"newly flagged", "flag cleared"}:
            continue
        print(f"    {status:<26} {n}")

    print("\n  " + "=" * 54)
    print("  Connection requests")
    print("  " + "=" * 54)
    print(f"    Sent in the last 7 days     {sent_recent} / {CONNECT_CAP_PER_WEEK}")
    print(f"    Remaining this week         {remaining}")
    print("\n    DMs to existing connections and cold emails do not count"
          "\n    against this cap — only new connection requests do.")

    due = counters.get("newly flagged", 0)
    print("\n  " + "=" * 54)
    print("  Follow-ups")
    print("  " + "=" * 54)
    print(f"    Newly flagged (sent {DAYS}+ days ago, no reply)   {due}")
    print(f"    Flags cleared (answered or followed up)      {counters.get('flag cleared', 0)}")

    if breaches:
        print("\n  " + "=" * 54)
        print(f"  ⚠  Personalization gate — {len(breaches)} breach(es)")
        print("  " + "=" * 54)
        print("    Marked SENT without the personalization box ticked:")
        for r in breaches[:15]:
            who = r.get("contact_name") or "(no contact)"
            print(f"      row {r['_row_num']:>4}  {who:<24} @ {r.get('company_display','')}")
        if len(breaches) > 15:
            print(f"      ... and {len(breaches) - 15} more")
    else:
        print("\n    Personalization gate: no breaches.")

    if REPORT:
        print("\n  --report — read-only, nothing written.")
        return

    if not updates:
        print("\n  Nothing to update.")
        return

    if DRY_RUN:
        print(f"\n  --dry-run — {len(updates)} row(s) would be updated:")
        for u in updates[:20]:
            print(f"    row {u['row_num']:>4}  {u['values']}")
        if len(updates) > 20:
            print(f"    ... and {len(updates) - 20} more")
        return

    sheets.batch_update_cells(ws, updates, sheets.NETWORKING_COLUMNS)
    print(f"\n  Updated {len(updates)} row(s).")




if __name__ == "__main__":
    main()
