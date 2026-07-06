"""
greenhouse_sources.py — Fetches jobs from target companies via the
public Greenhouse jobs board API. No auth required.
"""

import json
import os
import sys
import time
from html.parser import HTMLParser

import requests

BASE = os.path.dirname(__file__)

# ── Load target companies ─────────────────────────────────────────────────────

_config_path = os.path.join(BASE, "config", "target_companies.json")
with open(_config_path) as f:
    _config = json.load(f)

GREENHOUSE_SLUGS = _config.get("greenhouse_slugs", [])

# ── Title filter ──────────────────────────────────────────────────────────────

from config.filters import detect_remote

_search_config = json.loads(open(os.path.join(BASE, "config", "search_config.json")).read())
TITLE_TERMS = _search_config.get("title_filter_terms", [])

def _is_relevant(title: str) -> bool:
    t = title.strip().lower()
    return any(term in t for term in TITLE_TERMS)

# ── HTML stripping ────────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    stripper = _HTMLStripper()
    stripper.feed(raw)
    return stripper.get_text()

# ── Fetch one company ─────────────────────────────────────────────────────────

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

def _fetch_company(slug: str) -> list:
    """Returns all normalized jobs for a slug with no title filtering."""
    url = GREENHOUSE_API.format(slug=slug)
    try:
        resp = requests.get(url, params={"content": "true"}, timeout=15)
        if resp.status_code == 404:
            print(f"    [greenhouse] {slug} not on Greenhouse — skipping", file=sys.stderr)
            return []
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [greenhouse] {slug} request failed: {e}", file=sys.stderr)
        return []

    results = []
    for job in resp.json().get("jobs", []):
        title         = job.get("title", "")
        location_name = (job.get("location") or {}).get("name", "")
        description   = _strip_html(job.get("content", ""))[:8000]

        results.append({
            "job_id":      f"gh_{slug}_{job['id']}",
            "title":       title,
            "company":     slug.capitalize(),
            "location":    location_name,
            "remote":      detect_remote(title, location_name, description),
            "salary_text": None,
            "url":         job.get("absolute_url", ""),
            "description": description,
            "source":      "Greenhouse",
            "posted_at":   job.get("updated_at", ""),
        })

    return results

# ── Public entry point ────────────────────────────────────────────────────────

def fetch_greenhouse_jobs() -> list:
    print(f"  [Greenhouse] Fetching from {len(GREENHOUSE_SLUGS)} companies:")
    for slug in GREENHOUSE_SLUGS:
        print(f"    {slug}")

    all_jobs = []
    for slug in GREENHOUSE_SLUGS:
        all_jobs.extend(_fetch_company(slug))
        time.sleep(0.5)

    # Filter to relevant titles only — same logic as job_search.py pre-filter
    before = len(all_jobs)
    relevant_jobs = [j for j in all_jobs if _is_relevant(j["title"])]
    print(f"    → {len(relevant_jobs)} relevant jobs out of {before} total across all companies")
    return relevant_jobs

if __name__ == "__main__":
    jobs = fetch_greenhouse_jobs()
    print(f"\nTotal jobs found: {len(jobs)}")
