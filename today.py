"""
today.py — The only view Juhi opens: up to 5 referral + 5 networking rows, each with a draft.

Rows without a draft are not shown. Stale referrals are not shown. Sent rows
are not shown. What's left is the send block: company, who, why them, the
link, the note, and which cell to stamp when it's sent.

Prints to the terminal and rewrites the "Today" tab in the sheet (a view —
regenerated every run, never the source of anything).

Usage:
    python3 today.py            print + refresh the Today tab
    python3 today.py --print    print only
"""

import re
import sys
from datetime import datetime

import sheets

TODAY_TAB = "Today"
TODAY_COLUMNS = ["lane", "company", "who", "why_them", "link", "note", "when_sent_mark", "source_row"]
MAX_ROWS = 5


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


def collect() -> list:
    ss = sheets._spreadsheet()
    ref = sheets.get_all_rows_with_numbers(ss.worksheet(sheets.REFERRALS_TAB), formulas=True)
    net = sheets.get_all_rows_with_numbers(ss.worksheet(sheets.NETWORKING_TAB))

    out, seen_roles = [], set()
    for r in ref:
        # FORMULA rendering returns booleans/numbers for typed cells — normalize.
        r = {k: (v if k == "_row_num" else ("" if v is None else str(v))) for k, v in r.items()}
        if not (r.get("note_to_send", "") or "").strip():
            continue
        # The same job often arrives from two sources under two ids; show it once.
        role_key = ((r.get("company", "") or "").lower(), (r.get("title", "") or "").lower())
        if role_key in seen_roles:
            continue
        seen_roles.add(role_key)
        if (r.get("stale", "") or "").upper() == "TRUE":
            continue
        if any((r.get(k, "") or "").strip() for k in ("sent_1", "sent_2", "sent_rec")):
            continue
        who = _label(r.get("referrer_1", "")) or _label(r.get("recruiter", "")) or "hiring manager (search link)"
        link = _url(r.get("referrer_1", "")) or _url(r.get("recruiter", "")) or _url(r.get("fallback_contact", ""))
        out.append({
            "lane": "referral", "company": r.get("company", ""), "who": who,
            "why_them": f"{r.get('title','')} · score {r.get('score','')}",
            "link": link, "note": r.get("note_to_send", ""),
            "when_sent_mark": f"Referrals!sent_1 (row {r['_row_num']})",
            "source_row": f"Referrals:{r['_row_num']}", "_sort": (0, -_score(r)),
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
            "link": r.get("link", ""), "note": r.get("draft_body", ""),
            "when_sent_mark": f"Networking!status=SENT + sent_date (row {r['_row_num']})",
            "source_row": f"Networking:{r['_row_num']}", "_sort": (1, int(r.get("priority", "9") or 9)),
        })
    out.sort(key=lambda x: x["_sort"])
    ref_rows = [o for o in out if o["lane"] == "referral"][:MAX_ROWS]
    net_rows = [o for o in out if o["lane"] == "networking"][:MAX_ROWS]
    return ref_rows + net_rows


def main():
    rows = collect()
    print(f"\n  TODAY — {datetime.now():%a %b %d} — {len(rows)} row(s) with a draft in hand\n")
    if not rows:
        print("  Nothing drafted yet. Run: python3 draft_notes.py\n")
    for i, r in enumerate(rows, 1):
        print(f"  {i}. [{r['lane']}] {r['company']} → {r['who']}")
        print(f"     why: {r['why_them'][:100]}")
        print(f"     link: {r['link'][:90]}")
        print("     " + r["note"].replace("\n", "\n     ")[:600])
        print(f"     mark sent in: {r['when_sent_mark']}\n")

    if "--print" in sys.argv:
        return
    ws = sheets.open_or_create_tab(TODAY_TAB, TODAY_COLUMNS, rows=50)
    ws.clear()
    values = [TODAY_COLUMNS] + [[r[c] for c in TODAY_COLUMNS] for r in rows]
    ws.update(values=values, range_name="A1", value_input_option="RAW")
    print(f"  Today tab refreshed ({len(rows)} row(s)).")


if __name__ == "__main__":
    main()
