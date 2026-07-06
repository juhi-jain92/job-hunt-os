"""
sheets.py — All Google Sheets read/write operations for Job Hunt OS.
Nothing in this file fetches jobs or scores them — it only reads from
and writes to the single "Job Hunt OS" spreadsheet.
"""

import os
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

# Path to the service account key file
CREDS_PATH = os.path.join(os.path.dirname(__file__), "credentials", "sheets_key.json")
SHEET_NAME  = "Job Hunt OS"
OWNER_EMAIL = os.getenv("GOOGLE_SHEET_OWNER_EMAIL", "anchit008@gmail.com")  # sheet gets shared here on first create

# These scopes tell Google what the service account is allowed to do:
# - spreadsheets: read/write cell data
# - drive: needed to search for the sheet by name and create it if missing
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Exact column order in the sheet — must match the header row
COLUMNS = [
    "job_id", "title", "company", "location", "remote", "salary_text", "url",
    "source", "posted_at", "ai_score", "domain_score", "match_flag",
    "recommended_track", "cover_letter", "status", "notes", "description",
]

# Maps column name → column number (1-based) so we can update specific cells later
COL_INDEX = {col: i + 1 for i, col in enumerate(COLUMNS)}


def _client():
    """Creates an authenticated gspread client using the service account key."""
    creds = Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    return gspread.authorize(creds)


def open_or_create_sheet():
    """
    Returns the first worksheet of 'Job Hunt OS'.
    If the spreadsheet doesn't exist yet, creates it and shares it with OWNER_EMAIL.
    If the sheet is empty, writes the header row.
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

    sheet = spreadsheet.sheet1

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
            job.get("job_id",      ""),
            job.get("title",       ""),
            job.get("company",     ""),
            job.get("location",    ""),
            job.get("remote",      "Unknown"),
            job.get("salary_text") or "",
            job.get("url",         ""),
            job.get("source",      ""),
            job.get("posted_at",   ""),
            "",       # ai_score       — filled by scorer (step 2b)
            "",       # adtech_score   — filled by scorer (step 2b)
            "",       # match_flag     — filled by scorer (step 2b)
            "",       # recommended_track — filled by scorer (step 2b)
            "",       # cover_letter   — filled by cover letter step (step 2c)
            "new",    # status         — default until processed
            "",       # notes
            (job.get("description") or "")[:8000],  # description — up to 8000 chars
        ])

    # append_rows sends all rows in a single API call (much faster than one at a time)
    sheet.append_rows(rows, value_input_option="USER_ENTERED")
    return len(new_jobs)


def update_scores(sheet, job_id: str, ai_score, domain_score, match_flag: str, recommended_track: str):
    """
    Finds the row for a given job_id and writes scoring results into it.
    Called once per job by scorer.py in step 2b.
    """
    cell = sheet.find(job_id, in_column=1)
    if not cell:
        print(f"  [warning] job_id not found in sheet: {job_id}")
        return
    row = cell.row
    sheet.update_cell(row, COL_INDEX["ai_score"],          ai_score)
    sheet.update_cell(row, COL_INDEX["domain_score"],      domain_score)
    sheet.update_cell(row, COL_INDEX["match_flag"],        match_flag)
    sheet.update_cell(row, COL_INDEX["recommended_track"], recommended_track)


def update_cover_letter(sheet, job_id: str, cover_letter: str, status: str):
    """
    Writes the generated cover letter and final status into a job's row.
    Called by cover_letter.py in step 2c.
    """
    cell = sheet.find(job_id, in_column=1)
    if not cell:
        print(f"  [warning] job_id not found in sheet: {job_id}")
        return
    row = cell.row
    sheet.update_cell(row, COL_INDEX["cover_letter"], cover_letter)
    sheet.update_cell(row, COL_INDEX["status"],       status)


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
    Writes all scoring results to the sheet in a single API call.

    Each item in `updates` is a dict with:
        row_num          int   — 1-based sheet row number
        ai_score         int/str
        domain_score     int/str
        match_flag       str   — track label
        recommended_track str  — "Tier X | TRACK"
        notes            str   — scorer reason
        status           str   — status value to write
        write_status     bool  — only write status if True (i.e. cell was empty)

    Column layout (1-based, after adding "remote" as col E):
        J=10 ai_score  K=11 domain_score  L=12 match_flag  M=13 recommended_track
        N=14 cover_letter (never touched)  O=15 status  P=16 notes
    """
    tab = sheet.title   # actual tab name, needed in A1 range notation
    data = []

    for u in updates:
        row = u["row_num"]
        # Columns J–M in one range (scores + flags)
        data.append({
            "range": f"'{tab}'!J{row}:M{row}",
            "values": [[
                u["ai_score"],
                u["domain_score"],
                u["match_flag"],
                u["recommended_track"],
            ]],
        })
        # Column P — notes / reason
        data.append({
            "range": f"'{tab}'!P{row}",
            "values": [[u["notes"]]],
        })
        # Column O — status (only when the cell was blank)
        if u.get("write_status"):
            data.append({
                "range": f"'{tab}'!O{row}",
                "values": [[u["status"]]],
            })

    if data:
        sheet.spreadsheet.values_batch_update({
            "valueInputOption": "USER_ENTERED",
            "data": data,
        })
