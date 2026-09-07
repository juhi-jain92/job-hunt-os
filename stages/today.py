"""
today.py — The only tab Juhi opens. Every drafted, unsent, non-stale row.

Each row carries the job link (what the role actually is), the contact link
(who to send it to), the draft, and a `sent` cell she fills in right here.

The Today tab is a view, rebuilt from scratch every run — with one exception:
before rebuilding, anything marked in `sent` is written back to the row it came
from (Referrals or Networking), so marking sent in Today is the same as marking
it at the source. That write-back is the only thing Today is the source of.

Usage:
    python3 -m stages.today                 write back marks, then refresh the tab
    python3 -m stages.today --absorb-only   only file the marks, no rebuild
    python3 -m stages.today --print         print only, no writes
"""

import re
import sys
from datetime import datetime

from lib import sheets

TODAY_TAB = "Today"
TODAY_COLUMNS = ["lane", "company", "who", "why_them", "job_link",
                 "contact_link", "note", "sent", "source_row"]


def _label(cell: str) -> str:
    m = re.match(r'^=HYPERLINK\("([^"]*)","(.*)"\)$', cell or "")
    return m.group(2) if m else (cell or "")


def _url(cell: str) -> str:
    m = re.match(r'^=HYPERLINK\("([^"]*)","(.*)"\)$', cell or "")
    return m.group(1) if m else ""


def _score(r):
    try:
        return float(r.get("score", 0) or 0)
    except ValueError:
        return 0


def absorb_marks() -> int:
    """
    Reads the Today tab as it stands and pushes anything marked in `sent` back
    to its source row. Runs before the rebuild, so a mark is never lost to the
    refresh that follows it.
    """
    try:
        ws = sheets.open_or_create_tab(TODAY_TAB, TODAY_COLUMNS, rows=200)
        rows = sheets.get_all_rows_with_numbers(ws)
    except Exception as exc:
        print(f"  [warning] could not read the Today tab to collect marks: {exc}")
        return 0

    today = datetime.now().strftime("%Y-%m-%d")
    marks = {}
    for r in rows:
        if not (r.get("sent", "") or "").strip():
            continue
        tab, _, ident = (r.get("source_row", "") or "").partition(":")
        if tab and ident:
            marks.setdefault(tab, set()).add(ident.strip())
    if not marks:
        return 0

    # Look the row up by its own id, never by the row number it happened to
    # occupy when the view was built — the source tabs get rebuilt and reordered
    # between runs, and a stale row number stamps the wrong role.
    ref_updates, net_updates = [], []
    if marks.get("Referrals"):
        ref_ws = sheets.get_referrals_tab()
        for r in sheets.get_all_rows_with_numbers(ref_ws):
            if (r.get("job_id", "") or "").strip() in marks["Referrals"] \
                    and not (r.get("sent_1", "") or "").strip():
                ref_updates.append({"row_num": r["_row_num"], "values": {"sent_1": today}})
        if ref_updates:
            sheets.batch_update_cells(ref_ws, ref_updates, sheets.REFERRALS_COLUMNS)
    if marks.get("Networking"):
        net_ws = sheets.get_networking_tab()
        for r in sheets.get_all_rows_with_numbers(net_ws):
            if (r.get("outreach_id", "") or "").strip() in marks["Networking"] \
                    and (r.get("status", "") or "").upper() != "SENT":
                net_updates.append({"row_num": r["_row_num"],
                                    "values": {"status": "SENT", "sent_date": today}})
        if net_updates:
            sheets.batch_update_cells(net_ws, net_updates, sheets.NETWORKING_COLUMNS)

    n = len(ref_updates) + len(net_updates)
    if n:
        print(f"  Marked {n} row(s) as sent today, back at the source.")
    return n


def collect() -> list:
    ref = sheets.get_all_rows_with_numbers(sheets.get_referrals_tab(), formulas=True)
    net = sheets.get_all_rows_with_numbers(sheets.get_networking_tab())

    out = []
    for r in ref:
        if not (r.get("note_to_send", "") or "").strip():
            continue
        if (r.get("stale", "") or "").upper() == "TRUE":
            continue
        if any((r.get(k, "") or "").strip() for k in ("sent_1", "sent_2", "sent_rec")):
            continue
        who = _label(r.get("referrer_1", "")) or _label(r.get("recruiter", "")) \
            or _label(r.get("fallback_contact", "")) or "hiring manager (search link)"
        contact = _url(r.get("referrer_1", "")) or _url(r.get("recruiter", "")) \
            or _url(r.get("fallback_contact", ""))
        out.append({
            "lane": "referral", "company": r.get("company", ""), "who": who,
            "why_them": f"{r.get('title','')} · score {r.get('score','')}",
            "job_link": r.get("job_url", ""),
            "contact_link": contact,
            "note": r.get("note_to_send", ""),
            "sent": "",
            "source_row": f"Referrals:{r.get('job_id','')}",
            "_sort": (0, -_score(r)),
        })

    for r in net:
        if not (r.get("draft_body", "") or "").strip():
            continue
        if (r.get("status", "") or "").upper() != "PROSPECT":
            continue
        out.append({
            "lane": "networking", "company": r.get("company_display", ""),
            "who": r.get("contact_name", "") or "(pick from link)",
            "why_them": r.get("personalization_hook", "") or (r.get("notes", "") or "")[:80],
            "job_link": r.get("job_url", "") or r.get("careers_url", ""),
            "contact_link": r.get("link", ""),
            "note": r.get("draft_body", ""),
            "sent": "",
            "source_row": f"Networking:{r.get('outreach_id','')}",
            "_sort": (1, int(r.get("priority", "9") or 9)),
        })

    out.sort(key=lambda x: x["_sort"])
    return out


def main():
    if "--print" not in sys.argv:
        absorb_marks()
    if "--absorb-only" in sys.argv:
        return

    rows = collect()
    warm = sum(1 for r in rows if r["lane"] == "referral")
    print(f"\n  TODAY — {datetime.now():%a %b %d} — {len(rows)} row(s) ready to send "
          f"({warm} referral, {len(rows) - warm} networking)\n")
    if not rows:
        print("  Nothing drafted yet. Run: python3 -m stages.draft_notes\n")
    for i, r in enumerate(rows, 1):
        print(f"  {i}. [{r['lane']}] {r['company']} → {r['who']}")
        print(f"     why:  {r['why_them'][:100]}")
        if r["job_link"]:
            print(f"     job:  {r['job_link'][:90]}")
        print(f"     who:  {r['contact_link'][:90]}")
        print("     " + r["note"].replace("\n", "\n     ")[:600] + "\n")

    if "--print" in sys.argv:
        return

    ws = sheets.open_or_create_tab(TODAY_TAB, TODAY_COLUMNS, rows=max(50, len(rows) + 20))
    ws.clear()
    values = [TODAY_COLUMNS] + [[r[c] for c in TODAY_COLUMNS] for r in rows]
    ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")
    print(f"  Today tab refreshed ({len(rows)} row(s)). "
          f"Mark the `sent` column here; the next run files it for you.")


if __name__ == "__main__":
    main()
