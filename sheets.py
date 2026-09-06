"""
sheets.py — All Google Sheets read/write operations for Job Hunt OS.
Nothing in this file fetches jobs or scores them — it only reads from
and writes to the single "Job Hunt OS" spreadsheet.
"""

import os
import gspread
from google.oauth2.service_account import Credentials

# Path to the service account key file
CREDS_PATH = os.path.join(os.path.dirname(__file__), "credentials", "sheets_key.json")
SHEET_NAME  = "Job Hunt OS"
OWNER_EMAIL = "juhijaindtu@gmail.com"  # sheet gets shared here on first create

# These scopes tell Google what the service account is allowed to do:
# - spreadsheets: read/write cell data
# - drive: needed to search for the sheet by name and create it if missing
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Exact column order in the sheet — must match the header row.
# score is the single 0-10 total; the referral lane gates on score >= 7.
# Everything qualitative lives in notes as prose.
COLUMNS = [
    "job_id", "title", "company", "location", "source", "posted_at",
    "score", "status", "notes", "url", "description",
]

# Maps column name → column number (1-based) so we can update specific cells later
COL_INDEX = {col: i + 1 for i, col in enumerate(COLUMNS)}

# ---------- Referral engine tabs ----------

CONTACTS_TAB   = "Contacts"
TARGETS_TAB    = "Targets"
REFERRALS_TAB  = "Referrals"    # referral lane — one row per 7+ role
NETWORKING_TAB = "Networking"   # networking lane — one row per cold prospect

CONTACTS_COLUMNS = [
    "contact_id", "owner", "full_name", "first_name", "linkedin_url", "email",
    "company_raw", "company_norm", "title", "seniority_hint", "connected_on",
    "tie_basis", "tie_type", "tier", "last_contacted", "outreach_count",
    "source_file", "ingested_at", "notes",
]

TARGETS_COLUMNS = [
    "company_norm", "company_display", "size_class", "niche", "product_lines",
    "source", "best_job_id", "best_tier", "role_posted_at", "first_degree_count",
    "dormant_count", "route", "linkedin_people_url", "linkedin_isb_url",
    "linkedin_dtu_url", "careers_url", "news_search_url", "digest",
    "digest_generated_at", "last_recommended_on", "recommend_count", "status", "notes",
]

# Referral lane. One row per role scoring 7+, because the daily question is
# per-role: "does this job have a warm path, and through whom?" Three contact
# slots — two people plus a recruiter — rather than a row per contact, so
# forty roles fit on one screen.
#
# referrer_1, referrer_2, recruiter and fallback_contact are written as
# =HYPERLINK() formulas, so the name itself is the click target and no
# separate URL column is needed.
#
# tier is deliberately absent: every row here is already 7+ by construction.
REFERRALS_COLUMNS = [
    "job_id", "title", "company", "location", "source", "posted_at",
    "score", "notes",
    "first_degree_available", "referrer_1", "referrer_1_owner",
    "referrer_2", "referrer_2_owner", "recruiter",
    "note_to_send", "fallback_contact",
    "sent_1", "sent_2", "sent_rec", "followup_due",
    "story_id", "drafted_on", "stale",
]

# Networking lane. Column order follows the daily send block, not
# normalized-data shape: what's due → who → read the draft → check the hook →
# send → mark it. Join keys sit at the far right so they can be hidden.
NETWORKING_COLUMNS = [
    "outreach_id", "due_date", "priority", "status", "contact_name",
    "company_display", "job_open", "role_title", "channel", "message_shape", "owner",
    "link", "subject", "draft_body", "personalization_hook", "personalized",
    "digest", "sent_date", "response", "response_date", "follow_up_due",
    "follow_up_flag", "follow_up_sent", "job_id", "contact_id", "company_norm",
    "match_confidence", "generated_at", "notes", "story_id", "drafted_on",
]

# Statuses a human sets by hand — scripts must never overwrite these rows.
USER_STATUSES = {"sent", "replied", "closed", "skipped"}
OUTREACH_USER_STATUSES = USER_STATUSES  # retained for existing callers


def hyperlink(url: str, label: str) -> str:
    """
    A clickable cell. Written with USER_ENTERED so Sheets evaluates it.
    Falls back to plain text when there is no URL to point at.
    """
    if not url:
        return label or ""
    safe = (label or url).replace('"', "'")
    return f'=HYPERLINK("{url}","{safe}")'


def _client():
    """Creates an authenticated gspread client using the service account key."""
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


def _spreadsheet():
    """
    Opens the 'Job Hunt OS' spreadsheet, creating and sharing it if missing.
    Shared by open_or_create_sheet() and open_or_create_tab().
    """
    client = _client()
    try:
        spreadsheet = client.open(SHEET_NAME)
        print(f"  Opened existing sheet: '{SHEET_NAME}'")
    except gspread.SpreadsheetNotFound:
        spreadsheet = client.create(SHEET_NAME)
        # Share with your Google account so you can open it in your browser
        spreadsheet.share(OWNER_EMAIL, perm_type="user", role="writer", notify=False)
        print(f"  Created new sheet '{SHEET_NAME}' and shared with {OWNER_EMAIL}")
    return spreadsheet


def col_letter(n: int) -> str:
    """1 → A, 26 → Z, 27 → AA. The Outreach tab runs past column Z."""
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def open_or_create_tab(tab_name: str, columns: list, rows: int = 2000):
    """
    Returns the named worksheet, creating it with a header row if missing.

    If the existing header is a strict prefix of `columns`, the missing columns
    are appended in place — sheet1 never got this, and new tracking columns
    are expected as the workflow settles.
    """
    ss = _spreadsheet()
    try:
        ws = ss.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=tab_name, rows=rows, cols=len(columns))
        print(f"  Created tab '{tab_name}'")

    header = ws.row_values(1)
    if not header or header[0] != columns[0]:
        ws.update(values=[columns], range_name="A1", value_input_option="USER_ENTERED")
        print(f"  Wrote header row on '{tab_name}'")
    elif header == columns[: len(header)] and len(header) < len(columns):
        start = col_letter(len(header) + 1)
        ws.update(
            values=[columns[len(header):]],
            range_name=f"{start}1",
            value_input_option="USER_ENTERED",
        )
        print(f"  Extended '{tab_name}' header with {len(columns) - len(header)} new column(s)")
    elif header != columns:
        raise RuntimeError(
            f"Header drift on '{tab_name}'.\n  expected: {columns}\n  found:    {header}"
        )

    return ws


def get_contacts_tab():
    return open_or_create_tab(CONTACTS_TAB, CONTACTS_COLUMNS)


def get_targets_tab():
    return open_or_create_tab(TARGETS_TAB, TARGETS_COLUMNS)


def get_referrals_tab():
    return open_or_create_tab(REFERRALS_TAB, REFERRALS_COLUMNS)


def get_networking_tab():
    return open_or_create_tab(NETWORKING_TAB, NETWORKING_COLUMNS)


def get_existing_keys(ws, key_col: int = 1) -> set:
    """Generalization of get_existing_ids() for any tab's dedupe key column."""
    return set(ws.col_values(key_col)[1:])


def append_rows_dedup(ws, records: list, columns: list, key: str) -> int:
    """
    Appends records not already present (by `key`) in one API call.
    Each record is a dict; missing columns are written as blank.
    Returns the count of rows added.
    """
    existing = get_existing_keys(ws, key_col=columns.index(key) + 1)
    fresh = [r for r in records if r.get(key) and r[key] not in existing]
    if not fresh:
        return 0

    rows = [[str(r.get(col, "")) for col in columns] for r in fresh]
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    return len(fresh)


def batch_update_cells(ws, updates: list, columns: list):
    """
    Writes cell updates across a tab in one API call.

    Each item in `updates` is a dict:
        row_num  int  — 1-based sheet row number
        values   dict — {column_name: value}

    Contiguous columns are merged into a single range so a row touching
    status+notes costs one range entry, not two.
    """
    if not updates:
        return

    tab = ws.title
    index = {col: i + 1 for i, col in enumerate(columns)}
    data = []

    for u in updates:
        row = u["row_num"]
        cols = sorted(
            (index[name], value) for name, value in u["values"].items() if name in index
        )
        run = []
        for col_num, value in cols:
            if run and col_num == run[-1][0] + 1:
                run.append((col_num, value))
                continue
            if run:
                data.append(_range_entry(tab, row, run))
            run = [(col_num, value)]
        if run:
            data.append(_range_entry(tab, row, run))

    if data:
        ws.spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",
            "data": data,
        })


def _range_entry(tab: str, row: int, run: list) -> dict:
    """Builds one A1-notation range entry from a run of contiguous columns."""
    start = col_letter(run[0][0])
    end   = col_letter(run[-1][0])
    rng   = f"'{tab}'!{start}{row}" if start == end else f"'{tab}'!{start}{row}:{end}{row}"
    return {"range": rng, "values": [[v for _, v in run]]}


def guarded_update(ws, row_num: int, current_status: str, new_values: dict,
                   columns: list, user_statuses: set = USER_STATUSES) -> bool:
    """
    Writes new_values unless the row is user-owned. Returns False if skipped.
    Same contract the scorer uses to avoid clobbering hand-set statuses.
    """
    if (current_status or "").strip().lower() in user_statuses:
        return False
    batch_update_cells(ws, [{"row_num": row_num, "values": new_values}], columns)
    return True


def open_or_create_sheet():
    """
    Returns the first worksheet of 'Job Hunt OS'.
    If the spreadsheet doesn't exist yet, creates it and shares it with OWNER_EMAIL.
    If the sheet is empty, writes the header row.
    """
    sheet = _spreadsheet().sheet1

    # Write header if missing or if first cell isn't "job_id" (e.g. after a manual clear)
    existing = sheet.get_all_values()
    if not existing or not existing[0] or existing[0][0] != "job_id":
        sheet.insert_row(COLUMNS, 1, value_input_option="USER_ENTERED")
        print("  Wrote header row.")

    return sheet


def get_existing_ids(sheet) -> set:
    """
    Reads all values in column A (job_id) and returns them as a set.
    The first row is the header 'job_id', so we skip it.
    This is how we avoid writing the same job twice across runs.
    """
    all_ids = sheet.col_values(1)  # column A, every row
    return set(all_ids[1:])        # [1:] skips the header


def append_new_jobs(sheet, jobs: list) -> int:
    """
    Compares incoming jobs against what's already in the sheet.
    Writes only the new ones. Returns the count of rows added.
    """
    existing = get_existing_ids(sheet)
    new_jobs  = [j for j in jobs if j.get("job_id") and j["job_id"] not in existing]

    if not new_jobs:
        print("  No new jobs — all fetched job_ids already exist in the sheet.")
        return 0

    # Build a 2D list (list of rows) — gspread can write all rows in one API call
    rows = []
    for job in new_jobs:
        rows.append([
            job.get("job_id",    ""),
            job.get("title",     ""),
            job.get("company",   ""),
            job.get("location",  ""),
            job.get("source",    ""),
            job.get("posted_at", ""),
            "",       # score — filled by scorer
            "new",    # status — default until processed
            "",       # notes
            job.get("url", ""),
            (job.get("description") or "")[:8000],
        ])

    # append_rows sends all rows in a single API call (much faster than one at a time)
    # table_range="A1" anchors the append to the header table, so leftover
    # blank-but-formatted rows can never push new data hundreds of rows down.
    sheet.append_rows(rows, value_input_option="USER_ENTERED", table_range="A1")
    return len(new_jobs)


def clear_data_rows(sheet):
    """
    Wipes all content from the sheet and re-writes the header row.
    Call this when you want a clean slate before a fresh run.
    """
    sheet.clear()  # deletes every cell including the header
    sheet.append_row(COLUMNS, value_input_option="USER_ENTERED")
    print("  Sheet cleared — header restored.")


def get_all_rows_with_numbers(sheet) -> list:
    """
    Returns every data row as a dict plus a '_row_num' key with its 1-based
    sheet row number (header is row 1, first data row is row 2).
    Used by the scorer so it knows exactly which row to update.
    """
    all_values = sheet.get_all_values()   # list of lists, header at index 0
    if not all_values:
        return []
    headers = all_values[0]
    rows = []
    for i, vals in enumerate(all_values[1:], start=2):
        # Pad short rows so every header has a value
        padded = vals + [""] * (len(headers) - len(vals))
        row = {headers[j]: padded[j] for j in range(len(headers))}
        row["_row_num"] = i
        rows.append(row)
    return rows


def batch_write_scores(sheet, updates: list):
    """
    Writes all scoring results in a single API call.

    Each item in `updates`:
        row_num       int  — 1-based sheet row number
        score         0-10 total (the referral lane gates on this)
        notes         str  — the scorer's reason as prose
        status        str
        write_status  bool — only write status if True (cell was blank/new)

    Ranges are derived from COL_INDEX, so reordering COLUMNS cannot silently
    write into the wrong column the way the old hardcoded letters could.
    """
    tab = sheet.title
    c = lambda name: col_letter(COL_INDEX[name])
    data = []

    for u in updates:
        row = u["row_num"]
        data.append({
            "range": f"'{tab}'!{c('score')}{row}",
            "values": [[u.get("score", "")]],
        })
        data.append({
            "range": f"'{tab}'!{c('notes')}{row}",
            "values": [[u.get("notes", "")]],
        })
        if u.get("write_status"):
            data.append({
                "range": f"'{tab}'!{c('status')}{row}",
                "values": [[u.get("status", "")]],
            })

    if data:
        sheet.spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",
            "data": data,
        })
