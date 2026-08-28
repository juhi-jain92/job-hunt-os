"""
contacts_ingest.py — Ingests LinkedIn connections exports into the Contacts tab.

Reads both CSVs (Juhi's and Anchit's), normalizes company names, infers
dormant ties from tenure windows, dedupes across owners, and writes to the
sheet. Idempotent: re-running with a fresh export updates company and title on
existing contacts (people change jobs) and appends anyone new.

Usage:
    python3 contacts_ingest.py                    ingest both configured CSVs
    python3 contacts_ingest.py --dry-run          parse and report, write nothing
    python3 contacts_ingest.py --stats            print a breakdown after parsing
    python3 contacts_ingest.py --report-unmatched top companies with no job match
    python3 contacts_ingest.py --files a.csv:juhi b.csv:anchit
"""

import csv
import hashlib
import io
import json
import os
import sys
from collections import Counter
from datetime import datetime

import sheets
from normalize import norm_company, seniority_hint

BASE = os.path.dirname(__file__)
CONNECTIONS_DIR = os.path.join(BASE, "data", "connections")
PAST_EMPLOYERS_PATH = os.path.join(BASE, "config", "past_employers.json")

DEFAULT_FILES = [
    (os.path.join(CONNECTIONS_DIR, "juhi_connections.csv"), "juhi"),
    (os.path.join(CONNECTIONS_DIR, "anchit_connections.csv"), "anchit"),
]

DRY_RUN           = "--dry-run" in sys.argv
STATS             = "--stats" in sys.argv
REPORT_UNMATCHED  = "--report-unmatched" in sys.argv

# LinkedIn header names → our column names. A LinkedIn rename is a one-line fix.
ALIASES = {
    "first name": "first_name",
    "last name": "last_name",
    "url": "linkedin_url",
    "email address": "email",
    "company": "company_raw",
    "position": "title",
    "connected on": "connected_on",
}


def parse_files_flag() -> list:
    """--files path:owner path:owner"""
    if "--files" not in sys.argv:
        return DEFAULT_FILES
    out = []
    for arg in sys.argv[sys.argv.index("--files") + 1:]:
        if arg.startswith("--"):
            break
        path, _, owner = arg.partition(":")
        out.append((path, owner or "juhi"))
    return out or DEFAULT_FILES


def read_connections(path: str):
    """
    Yields normalized dicts from a LinkedIn connections export.

    LinkedIn prepends a "Notes:" preamble whose length has changed between
    export versions, so the header row is located by scanning rather than
    skipping a fixed number of lines.
    """
    with open(path, encoding="utf-8-sig", newline="") as fh:
        lines = fh.read().splitlines()

    header_idx = None
    for i, line in enumerate(lines[:10]):
        cells = next(csv.reader([line]), [])
        keys = {c.strip().lower() for c in cells}
        if "first name" in keys and "last name" in keys:
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(
            f"{path}: no LinkedIn header row found in the first 10 lines.\n"
            f"  Expected a row containing 'First Name' and 'Last Name'.\n"
            f"  Saw: {lines[:5]}"
        )

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    for raw in reader:
        row = {
            ALIASES.get((k or "").strip().lower(), (k or "").strip().lower()):
            (v or "").strip()
            for k, v in raw.items()
        }
        if row.get("first_name") or row.get("last_name"):
            yield row


def parse_connected_on(value: str) -> str:
    """LinkedIn writes '23 Jun 2021'. Falls back to raw on locale variance."""
    for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value


def load_past_employers() -> list:
    """
    Tenure windows used to infer dormant ties.

    LinkedIn's export carries no employment history for connections — only
    their current company and the date you connected. So a connection made
    during a given tenure is inferred to be a colleague from that employer.
    The evidence goes into tie_basis so wrong guesses can be corrected by hand.
    """
    try:
        with open(PAST_EMPLOYERS_PATH, encoding="utf-8") as fh:
            return [e for e in json.load(fh).get("tenures", []) if e.get("employer")]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


DORMANT_AFTER_MONTHS = 18


def infer_tie(connected_on: str, tenures: list, today: datetime = None):
    """
    Returns (tie_type, tie_basis) from the connect date.

    A tie is dormant only when it is both attributable to a past employer and
    old enough to have gone quiet. Tenures are usually back-to-back, so the
    employer window alone would tag every contact dormant and surface nothing.
    """
    if not connected_on or len(connected_on) < 7:
        return "first_degree", ""

    today = today or datetime.now()
    ym = connected_on[:7]
    age_months = (today.year - int(ym[:4])) * 12 + (today.month - int(ym[5:7]))

    for t in tenures:
        start, end = t.get("start", ""), t.get("end", "") or "9999-12"
        if start <= ym <= end:
            if age_months >= DORMANT_AFTER_MONTHS:
                return "dormant", f"connected {ym}, during {t['employer']} tenure"
            return "first_degree", f"connected {ym}, during {t['employer']} tenure"

    return "first_degree", f"connected {ym}"


def build_contact(row: dict, owner: str, source_file: str, tenures: list) -> dict:
    first = row.get("first_name", "")
    last  = row.get("last_name", "")
    full  = f"{first} {last}".strip()
    company_raw  = row.get("company_raw", "")
    company_norm = norm_company(company_raw)
    linkedin_url = row.get("linkedin_url", "")
    connected_on = parse_connected_on(row.get("connected_on", ""))
    tie_type, tie_basis = infer_tie(connected_on, tenures)

    seed = linkedin_url.lower() or f"{full.lower()}|{company_norm}"
    contact_id = "c_" + hashlib.sha1(seed.encode()).hexdigest()[:16]

    return {
        "contact_id": contact_id,
        "owner": owner,
        "full_name": full,
        "first_name": first,
        "linkedin_url": linkedin_url,
        "email": row.get("email", ""),
        "company_raw": company_raw,
        "company_norm": company_norm,
        "title": row.get("title", ""),
        "seniority_hint": seniority_hint(row.get("title", "")),
        "connected_on": connected_on,
        "tie_basis": tie_basis,
        "tie_type": tie_type,
        "tier": "",
        "last_contacted": "",
        "outreach_count": "",
        "source_file": os.path.basename(source_file),
        "ingested_at": datetime.now().strftime("%Y-%m-%d"),
        "notes": "",
    }


def main():
    files = parse_files_flag()
    tenures = load_past_employers()

    if tenures:
        print(f"  Loaded {len(tenures)} tenure window(s) for dormant-tie inference")
    else:
        print("  [note] config/past_employers.json not found — all ties tagged first_degree")

    by_id = {}
    skipped_files = []

    for path, owner in files:
        if not os.path.exists(path):
            skipped_files.append(path)
            continue

        print(f"\n  Reading {os.path.basename(path)} (owner: {owner}) ...")
        count = 0
        for row in read_connections(path):
            contact = build_contact(row, owner, path, tenures)
            cid = contact["contact_id"]
            if cid in by_id and by_id[cid]["owner"] != owner:
                # Known to both — that is signal, not a duplicate.
                by_id[cid]["owner"] = "both"
            else:
                by_id.setdefault(cid, contact)
            count += 1
        print(f"    {count} rows parsed")

    if skipped_files:
        for path in skipped_files:
            print(f"  [warning] not found, skipped: {path}")

    contacts = list(by_id.values())
    if not contacts:
        sys.exit(
            "\nERROR: No contacts parsed. Export your LinkedIn connections "
            "(Settings → Data privacy → Get a copy of your data → Connections)\n"
            f"and save them to {CONNECTIONS_DIR}/"
        )

    print(f"\n  {len(contacts)} unique contacts after cross-owner dedupe")

    if STATS:
        print_stats(contacts)

    if REPORT_UNMATCHED:
        report_unmatched(contacts)

    if DRY_RUN:
        print("\n  --dry-run — nothing written to the sheet.")
        return

    ws = sheets.get_contacts_tab()
    existing = {
        r["contact_id"]: r
        for r in sheets.get_all_rows_with_numbers(ws)
        if r.get("contact_id")
    }

    new_records = [c for c in contacts if c["contact_id"] not in existing]
    added = sheets.append_rows_dedup(
        ws, new_records, sheets.CONTACTS_COLUMNS, "contact_id"
    )

    # People change jobs — refresh company and title on contacts we already have.
    updates = []
    for c in contacts:
        prior = existing.get(c["contact_id"])
        if not prior:
            continue
        changed = {}
        for field in ("company_raw", "company_norm", "title", "seniority_hint"):
            if prior.get(field, "") != c[field]:
                changed[field] = c[field]
        if changed:
            updates.append({"row_num": prior["_row_num"], "values": changed})

    if updates:
        sheets.batch_update_cells(ws, updates, sheets.CONTACTS_COLUMNS)

    print(f"\n  Added {added} new contact(s), updated {len(updates)} existing.")


def print_stats(contacts: list):
    print("\n  " + "=" * 46)
    print("  Breakdown")
    print("  " + "=" * 46)

    for label, key in [("Owner", "owner"), ("Tie type", "tie_type"),
                       ("Seniority", "seniority_hint")]:
        counts = Counter(c[key] for c in contacts)
        print(f"\n  {label}:")
        for value, n in counts.most_common():
            print(f"    {value or '(blank)':<24} {n}")

    companies = Counter(c["company_norm"] for c in contacts if c["company_norm"])
    print(f"\n  Top companies ({len(companies)} distinct):")
    for company, n in companies.most_common(15):
        print(f"    {company:<32} {n}")


def report_unmatched(contacts: list):
    """
    Companies in the contact list that no scored job mentions. Curating the
    alias file from this output is the cheapest way to improve join coverage.
    """
    print("\n  Checking contact companies against the jobs sheet ...")
    try:
        job_rows = sheets.get_all_rows_with_numbers(sheets.open_or_create_sheet())
    except Exception as e:
        print(f"  [warning] could not read jobs sheet: {e}")
        return

    job_companies = {norm_company(r.get("company", "")) for r in job_rows}
    job_companies.discard("")

    unmatched = Counter(
        c["company_norm"] for c in contacts
        if c["company_norm"] and c["company_norm"] not in job_companies
    )

    print(f"\n  Top 30 contact companies with no exact job match")
    print("  (add real equivalences to config/company_aliases.json)")
    print("  " + "-" * 46)
    for company, n in unmatched.most_common(30):
        print(f"    {company:<34} {n:>4} contact(s)")


if __name__ == "__main__":
    main()
