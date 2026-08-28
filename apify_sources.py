"""
apify_sources.py — Fetches jobs from two Apify actors and normalizes each
into the same schema used by JSearch: {job_id, title, company, location,
url, description, source, posted_at}.
"""

import hashlib
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()
APIFY_TOKEN = os.getenv("APIFY_TOKEN")

APIFY_BASE = "https://api.apify.com/v2/acts"


def _run_actor(actor_slug: str, input_data: dict, timeout_secs: int = 180) -> list:
    """
    Runs an Apify actor synchronously and returns its dataset items as a list.
    If the actor fails or times out, logs a warning and returns [] so one bad
    source never stops the whole run.
    """
    url = f"{APIFY_BASE}/{actor_slug}/run-sync-get-dataset-items"
    try:
        resp = requests.post(
            url,
            json=input_data,
            params={"token": APIFY_TOKEN},
            timeout=timeout_secs + 15,  # HTTP timeout slightly longer than actor's own timeout
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"  [warning] Apify actor '{actor_slug}' failed: {e}", file=sys.stderr)
        return []


def _stable_id(prefix: str, *parts) -> str:
    """
    Generates a stable job_id by hashing the given parts.
    Used when the actor output has no native unique ID field.
    """
    raw = "_".join(str(p) for p in parts if p)
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


# ── 1. VC Portfolio Jobs ──────────────────────────────────────────────────────

def fetch_vc_portfolio_jobs() -> list:
    """
    Fetches PM-related jobs from a16z, YC, and Sequoia portfolio companies
    via parseforge/vc-portfolio-jobs-aggregator-scraper.
    Note: this actor doesn't return job descriptions — description will be "".
    """
    print("  [Apify] Fetching VC portfolio jobs (a16z, YC, Sequoia) ...")
    items = _run_actor(
        "parseforge~vc-portfolio-jobs-aggregator-scraper",
        {
            "firms":    ["a16z", "ycombinator", "sequoia"],
            "keyword":  "product",  # narrows to PM-adjacent roles
            "maxItems": 100,
        },
    )

    results = []
    for item in items:
        if item.get("error"):  # actor marks individual failures with an error field
            continue
        apply_url = item.get("applyUrl", "")
        vc_title  = item.get("title", "")
        vc_loc    = item.get("location", "")
        results.append({
            "job_id":      _stable_id("vc", apply_url, vc_title),
            "title":       vc_title,
            "company":     item.get("company", ""),
            "location":    vc_loc,
            "url":         apply_url,
            "description": "",  # not in this actor's output
            "source":      "a16z/VC",
            "posted_at":   item.get("postedAt"),
        })

    print(f"    → {len(results)} jobs")
    return results


# ── 2. Wellfound ──────────────────────────────────────────────────────────────

def fetch_wellfound_jobs() -> list:
    """
    Fetches PM roles on Wellfound (Remote + Seattle) via
    blackfalcondata/wellfound-scraper. enrichDetail=True gets full descriptions.
    """
    print("  [Apify] Fetching Wellfound jobs ...")
    items = _run_actor(
        "blackfalcondata~wellfound-scraper",
        {
            "roles":        ["product-manager"],
            "location":     ["remote", "seattle"],
            "maxResults":   50,
            "enrichDetail": True,  # fetches full job description per listing
        },
    )

    results = []
    for item in items:
        # Location: actor returns a list of city names
        locs     = item.get("locationNames") or []
        location = ", ".join(locs)

        native_id = item.get("id")
        wf_title  = item.get("title", "")
        wf_desc   = item.get("description", "")
        results.append({
            "job_id":      f"wf_{native_id}" if native_id else _stable_id("wf", item.get("portalUrl", "")),
            "title":       wf_title,
            "company":     item.get("companyName", ""),
            "location":    location,
            "url":         item.get("detailUrl") or item.get("portalUrl", ""),
            "description": wf_desc,
            "source":      "Wellfound",
            "posted_at":   item.get("postedAt"),
        })

    print(f"    → {len(results)} jobs")
    return results

