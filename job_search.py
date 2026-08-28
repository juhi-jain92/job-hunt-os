"""
job_search.py — Orchestrates all job fetching: JSearch (RapidAPI) for broad
PM queries, plus three Apify actors (VC portfolio, Wellfound, HN Who's Hiring).
Merges everything into one deduped list. No filtering — scoring happens later.
"""

import json
import os
import sys
import time
from collections import Counter
import requests
from dotenv import load_dotenv
import sheets              # Google Sheets read/write helper
import apify_sources       # Apify actor fetchers (VC portfolio, Wellfound)
import greenhouse_sources  # Greenhouse public jobs board API

# ---------- 0. Load context store ----------
_search_config    = json.loads(open(os.path.join(os.path.dirname(__file__), "config", "search_config.json")).read())
QUERIES           = _search_config.get("search_queries", [])
TITLE_TERMS       = _search_config.get("title_filter_terms", [])
DATE_POSTED_FILTER = _search_config.get("date_posted_filter", "week")

# ---------- 1. Load secrets ----------
load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
if not RAPIDAPI_KEY or RAPIDAPI_KEY == "your_key_here":
    sys.exit("ERROR: Set RAPIDAPI_KEY in your .env file.")

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
if not APIFY_TOKEN:
    sys.exit("ERROR: Set APIFY_TOKEN in your .env file.")

# ---------- 2. JSearch ----------
JSEARCH_URL = "https://jsearch.p.rapidapi.com/search-v2"
JSEARCH_HEADERS = {
    "x-rapidapi-host": "jsearch.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}

def fetch_jsearch(query: str) -> list:
    """
    Calls JSearch with a plain query. num_pages=5 returns up to 50 results
    and counts as 1 API request. At 10k/month we have ~333 requests/day;
    a full run costs 10 requests, leaving headroom for multiple daily runs.
    """
    params = {
        "query":      query,
        "page":       "1",
        "num_pages":  "5",
        "date_posted": DATE_POSTED_FILTER,
    }
    for attempt in (1, 2):
        try:
            resp = requests.get(JSEARCH_URL, headers=JSEARCH_HEADERS, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json().get("data", {}).get("jobs", [])
        except requests.Timeout as e:
            if attempt == 1:
                print(f"  [retry] JSearch timed out for {query!r} — retrying in 10 s ...", file=sys.stderr)
                time.sleep(10)
            else:
                print(f"  [warning] JSearch timed out again for {query!r} — skipping.", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  [warning] JSearch failed for {query!r}: {e}", file=sys.stderr)
            return []  # non-timeout errors: do not retry
    return []


def normalize_jsearch(job: dict) -> dict:
    """
    Maps a raw JSearch job object to the shared schema.
    All Apify sources use this same shape so the whole list is uniform.
    """
    city  = job.get("job_city")
    state = job.get("job_state")
    if city and state:
        location = f"{city}, {state}"
    elif city:
        location = city
    else:
        location = job.get("job_country")

    title_raw = job.get("job_title") or ""
    desc_raw  = (job.get("job_description") or "").strip()

    return {
        "job_id":      job.get("job_id"),
        "title":       title_raw,
        "company":     job.get("employer_name"),
        "location":    location,
        "url":         job.get("job_apply_link") or job.get("job_google_link"),
        "description": desc_raw[:8000],
        "source":      job.get("job_publisher"),
        "posted_at":   job.get("job_posted_at_datetime_utc"),
    }


# ---------- 3. Run JSearch ----------
print(f"\n{'='*50}")
print(f"JSearch — {len(QUERIES)} queries")
print('='*50)

collected: list = []
seen_ids:  set  = set()

for query in QUERIES:
    print(f"  Querying: {query!r} ...")
    for job in fetch_jsearch(query):
        jid = job.get("job_id")
        if jid and jid not in seen_ids:
            seen_ids.add(jid)
            collected.append(normalize_jsearch(job))
    print(f"    → running total: {len(collected)}")
    time.sleep(1)

print(f"\nJSearch total: {len(collected)} unique jobs")

# ---------- 4. Run Apify sources ----------
print(f"\n{'='*50}")
print("Apify sources")
print('='*50)

for source_job_list in [
    apify_sources.fetch_vc_portfolio_jobs(),
    apify_sources.fetch_wellfound_jobs(),
    greenhouse_sources.fetch_greenhouse_jobs(),
]:
    for job in source_job_list:
        jid = job.get("job_id")
        if jid and jid not in seen_ids:
            seen_ids.add(jid)
            collected.append(job)

# ---------- 5. Pre-filter — title relevance ----------

from normalize import is_blocked

def is_relevant(job: dict) -> bool:
    if is_blocked(job.get("company", "")):
        return False
    title = (job.get("title") or "").strip().lower()
    return any(term in title for term in TITLE_TERMS)


before    = len(collected)
collected = [j for j in collected if is_relevant(j)]
after     = len(collected)

print(f"\n{'='*50}")
print(f"Pre-filter: {before} → {after} jobs  ({before - after} dropped)")
print('='*50)

counts = Counter(job.get("source", "unknown") for job in collected)
for source, count in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  {source:<30} {count}")

# ---------- 6. Append new jobs to sheet (ledger mode) ----------
sheet = sheets.open_or_create_sheet()
added = sheets.append_new_jobs(sheet, collected)
already_in_sheet = after - added
print(f"\nFound {added} new jobs out of {after} total fetched ({already_in_sheet} already in sheet)")
