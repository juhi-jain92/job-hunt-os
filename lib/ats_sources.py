"""
ats_sources.py — Public job-board fetchers for Ashby and Lever.

Greenhouse is only one of three boards the companies worth watching actually
use: of the Lenny 100, 20 are on Greenhouse and 56 are on Ashby or Lever, so a
Greenhouse-only pipeline cannot see most of them. Both APIs are public and need
no auth, and both are read here into the same row schema discovery already uses.

Boards are configured in config/target_companies.json:

    "ashby_slugs": ["openai", "notion", ...]
    "lever_slugs": ["palantir", ...]

Company display names come from config/ats_company_names.json when present, so
"thinkingmachines" shows up as "Thinking Machines" in the ledger.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE, "config", "target_companies.json")) as f:
    _config = json.load(f)

ASHBY_SLUGS = _config.get("ashby_slugs", [])
LEVER_SLUGS = _config.get("lever_slugs", [])

_search_config = json.loads(
    open(os.path.join(BASE, "config", "search_config.json")).read())
TITLE_TERMS = _search_config.get("title_filter_terms", [])

_names_path = os.path.join(BASE, "config", "ats_company_names.json")
try:
    with open(_names_path) as f:
        DISPLAY_NAMES = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    DISPLAY_NAMES = {}

TIMEOUT = 12


def _is_pm_relevant(title: str) -> bool:
    t = (title or "").strip().lower()
    return any(term in t for term in TITLE_TERMS)


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def text(self):
        return " ".join(" ".join(self._parts).split())


def _strip_html(html: str) -> str:
    if not html:
        return ""
    p = _HTMLStripper()
    try:
        p.feed(html)
    except Exception:
        return html
    return p.text()


def _display(slug: str) -> str:
    return DISPLAY_NAMES.get(slug, slug.replace("-", " ").title())


def _fetch_ashby(slug: str) -> list:
    """
    Ashby's job board API. includeCompensation is free and often carries the
    salary range the scorer needs to judge the comp dealbreaker honestly.
    """
    url = (f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
           f"?includeCompensation=true")
    try:
        r = requests.get(url, timeout=TIMEOUT,
                         headers={"User-Agent": "job-hunt-os"})
        if r.status_code != 200:
            return []
        jobs = (r.json() or {}).get("jobs") or []
    except Exception:
        return []

    out = []
    for j in jobs:
        title = j.get("title", "")
        if not _is_pm_relevant(title):
            continue
        desc = _strip_html(j.get("descriptionHtml", "") or j.get("descriptionPlain", ""))
        comp = j.get("compensation") or {}
        summary = comp.get("compensationTierSummary") or ""
        if summary:
            desc = f"Compensation: {summary}\n\n{desc}"
        out.append({
            "job_id":      f"ashby_{slug}_{j.get('id','')}",
            "title":       title,
            "company":     _display(slug),
            "location":    j.get("location", "") or "",
            "url":         j.get("jobUrl", "") or j.get("applyUrl", ""),
            "description": desc[:8000],
            "source":      "Ashby",
            "posted_at":   (j.get("publishedAt") or j.get("updatedAt") or "")[:19],
        })
    return out


def _fetch_lever(slug: str) -> list:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        r = requests.get(url, timeout=TIMEOUT,
                         headers={"User-Agent": "job-hunt-os"})
        if r.status_code != 200:
            return []
        jobs = r.json() or []
    except Exception:
        return []

    out = []
    for j in jobs:
        title = j.get("text", "")
        if not _is_pm_relevant(title):
            continue
        cats = j.get("categories") or {}
        # Lever timestamps are epoch milliseconds.
        posted = ""
        ms = j.get("createdAt")
        if isinstance(ms, (int, float)):
            from datetime import datetime, timezone
            posted = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        out.append({
            "job_id":      f"lever_{slug}_{j.get('id','')}",
            "title":       title,
            "company":     _display(slug),
            "location":    cats.get("location", "") or "",
            "url":         j.get("hostedUrl", "") or j.get("applyUrl", ""),
            "description": _strip_html(j.get("descriptionPlain") or j.get("description", ""))[:8000],
            "source":      "Lever",
            "posted_at":   posted,
        })
    return out


def fetch_ats_jobs() -> list:
    """Every PM-relevant posting across the configured Ashby and Lever boards."""
    tasks = [(_fetch_ashby, s) for s in ASHBY_SLUGS] + \
            [(_fetch_lever, s) for s in LEVER_SLUGS]
    if not tasks:
        return []
    print(f"  [Ashby/Lever] Fetching {len(ASHBY_SLUGS)} Ashby + "
          f"{len(LEVER_SLUGS)} Lever boards (8 at a time) ...")

    all_jobs = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for jobs in pool.map(lambda t: t[0](t[1]), tasks):
            all_jobs.extend(jobs)
    print(f"    → {len(all_jobs)} PM-relevant jobs")
    return all_jobs


if __name__ == "__main__":
    jobs = fetch_ats_jobs()
    print(f"\nTotal PM jobs found: {len(jobs)}")
    for j in jobs[:20]:
        print(f"  {j['company']:<22} {j['title'][:60]}")
