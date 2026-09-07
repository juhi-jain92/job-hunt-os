"""
referral_match.py — Builds the Referrals tab: one row per role scoring 7+.

Deterministic. No model calls, so --preview is exact rather than indicative:
what it prints is what it would write.

Per role it fills three contact slots:
  referrer_1, referrer_2   the two strongest first-degree or dormant contacts
  recruiter                a recruiter at the company, if one is in your network
  fallback_contact         a LinkedIn people-search link when nobody is inside

Contacts are ranked, not taken in sheet order, because two slots against eight
Google contacts is a choice about which ask to spend. First-degree beats
dormant, product beats non-product, and a recent connection beats an old one.

Match confidence gates the row. exact, alias and subset fill the slots; fuzzy
is never written without --allow-fuzzy, and even then it is flagged in notes.

Usage:
    python3 referral_match.py --preview 5      print the join, write nothing
    python3 referral_match.py                  write the Referrals tab
    python3 referral_match.py --min-score 9    top matches only
    python3 referral_match.py --fresh-only     roles posted in the last 48h
    python3 referral_match.py --allow-fuzzy
"""

import sys
from collections import Counter, defaultdict
from datetime import datetime

import sheets
from contact_extract import hunter_domain_search
from linkedin_urls import people_search_url
from normalize import is_blocked, match_company, norm_company


FRESH_HOURS = 48
AUTO_FILL_CONFIDENCE = {"exact", "alias", "subset"}
PEOPLE_SLOTS = 2

USER_OWNED_JOB_STATUSES = sheets.JOB_USER_STATUSES

# When nobody in either network is at the company, spend a Hunter credit to
# find a product leader to cold-email — but only for fresh, strong roles, and
# only a few a day: the free tier is 50 searches a month.
HUNTER_COLD_MIN_SCORE = 8
HUNTER_COLD_MAX_AGE_H = 14 * 24
HUNTER_COLD_CAP = 3
_PRODUCT_LEADER = ("head of product", "vp product", "vp, product", "vp of product",
                   "chief product", "director of product", "director, product",
                   "product director", "principal product", "staff product",
                   "group product")


def hunter_product_leader(company: str):
    """Best product-leadership contact Hunter has for a company, or None."""
    res = hunter_domain_search(company=company)
    if not res.get("available"):
        return None
    ranked = sorted(
        (e for e in res.get("emails", []) if e.get("name")),
        key=lambda e: (0 if any(t in (e.get("position") or "").lower() for t in _PRODUCT_LEADER)
                       else 1 if "product" in (e.get("position") or "").lower() else 2,
                       -(e.get("confidence") or 0)),
    )
    if not ranked or "product" not in (ranked[0].get("position") or "").lower():
        return None
    return ranked[0]


def _flag(name: str, default):
    if name not in sys.argv:
        return default
    try:
        return type(default)(sys.argv[sys.argv.index(name) + 1])
    except (IndexError, ValueError):
        return default


PREVIEW_MODE = "--preview" in sys.argv
PREVIEW_N    = _flag("--preview", 5)
LIMIT        = _flag("--limit", 0)
MIN_SCORE    = _flag("--min-score", 7)
ALLOW_FUZZY  = "--allow-fuzzy" in sys.argv
FRESH_ONLY   = "--fresh-only" in sys.argv


def qualifies(row: dict, min_score: int) -> bool:
    """The ledger's score column is the 0-10 total the scorer computed."""
    try:
        return float(row.get("score", "") or 0) >= min_score
    except ValueError:
        return False


def parse_posted(value: str):
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def hours_old(posted_at: str):
    dt = parse_posted(posted_at)
    return None if not dt else (datetime.now() - dt).total_seconds() / 3600


def load_contacts_by_company(rows: list) -> dict:
    index = defaultdict(list)
    for r in rows:
        key = (r.get("company_norm") or "").strip()
        if key:
            index[key].append(r)
    return index


def find_contacts(job_company: str, index: dict):
    """(contacts, confidence) for a job's company. Dict hit first."""
    key = norm_company(job_company)
    if not key:
        return [], None
    if key in index:
        return index[key], "exact"

    best = None
    rank = {"alias": 0, "exact": 0, "subset": 1, "fuzzy": 2}
    for candidate in index:
        conf = match_company(job_company, candidate)
        if conf and (best is None or rank[conf] < best[0]):
            best = (rank[conf], candidate, conf)
    return (index[best[1]], best[2]) if best else ([], None)


def contact_rank(contact: dict) -> tuple:
    """
    Sort key, lower is better. Two slots against many contacts is a decision
    about which ask to spend, so rank rather than take whoever comes first.
    """
    tie = (contact.get("tie_type") or "").strip()
    tie_score = 0 if tie == "first_degree" else 1 if tie == "dormant" else 2

    seniority = (contact.get("seniority_hint") or "").strip()
    sen_score = {"director+": 0, "exec": 0, "manager": 1, "ic": 2}.get(seniority, 3)

    title = (contact.get("title") or "").lower()
    product_score = 0 if "product" in title else 1

    # A recent connection is likelier to remember you.
    connected = (contact.get("connected_on") or "")
    recency = -(connected[:7] and int(connected[:4] + connected[5:7]) or 0)

    return (tie_score, product_score, sen_score, recency)


def is_recruiter(contact: dict) -> bool:
    return (contact.get("seniority_hint") or "").strip() == "recruiter"


def main():
    today = datetime.now().strftime("%Y-%m-%d")

    print("  Reading contacts ...")
    contact_rows = sheets.get_all_rows_with_numbers(sheets.get_contacts_tab())
    if not contact_rows:
        # Exit 0 so a scheduled run before the CSVs are ingested is a quiet
        # no-op, not a red X on the workflow.
        print("\n  Contacts tab is empty — run contacts_ingest.py first. Nothing to match.")
        return
    index = load_contacts_by_company(contact_rows)
    print(f"    {len(contact_rows)} contacts across {len(index)} companies")

    print("  Reading scored roles ...")
    job_rows = sheets.get_all_rows_with_numbers(sheets.open_or_create_sheet())

    eligible = [
        r for r in job_rows
        if qualifies(r, MIN_SCORE)
        and not is_blocked(r.get("company", ""))
        and (r.get("status", "") or "").lower() not in USER_OWNED_JOB_STATUSES
    ]
    if FRESH_ONLY:
        eligible = [r for r in eligible
                    if (hours_old(r.get("posted_at", "")) or 1e9) <= FRESH_HOURS]
    if LIMIT:
        eligible = eligible[:LIMIT]

    print(f"    {len(eligible)} roles scoring {MIN_SCORE}+"
          + (" posted in the last 48h" if FRESH_ONLY else ""))
    if not eligible:
        print("\n  Nothing to match. Score more roles, or lower --min-score.")
        return

    rows, counters = [], Counter()
    hunter_budget = HUNTER_COLD_CAP

    for job in eligible:
        company = job.get("company", "")
        matched, confidence = find_contacts(company, index)

        fuzzy_note = ""
        if confidence == "fuzzy":
            if ALLOW_FUZZY:
                fuzzy_note = (f"Fuzzy company match against "
                              f"'{matched[0].get('company_raw','')}' — confirm before sending. ")
                counters["fuzzy (flagged)"] += 1
            else:
                matched, confidence = [], None
                counters["fuzzy skipped"] += 1

        usable = matched if confidence in AUTO_FILL_CONFIDENCE or ALLOW_FUZZY else []
        recruiters = [c for c in usable if is_recruiter(c)]
        people = sorted([c for c in usable if not is_recruiter(c)], key=contact_rank)

        row = {
            "job_id": job.get("job_id", ""),
            "title": job.get("title", ""),
            "company": company,
            "location": job.get("location", ""),
            "source": job.get("source", ""),
            "posted_at": (job.get("posted_at", "") or "")[:10],
            "score": job.get("score", ""),
            "notes": fuzzy_note + (job.get("notes", "") or "")[:180],
            "first_degree_available": "TRUE" if people else "FALSE",
            "note_to_send": "",
            "sent_1": "", "sent_2": "", "sent_rec": "", "followup_due": "",
        }

        for i in range(PEOPLE_SLOTS):
            slot = i + 1
            if i < len(people):
                c = people[i]
                row[f"referrer_{slot}"] = sheets.hyperlink(
                    c.get("linkedin_url", ""), c.get("full_name", "")
                )
                row[f"referrer_{slot}_owner"] = c.get("owner", "")
            else:
                row[f"referrer_{slot}"] = ""
                row[f"referrer_{slot}_owner"] = ""

        row["recruiter"] = sheets.hyperlink(
            recruiters[0].get("linkedin_url", ""), recruiters[0].get("full_name", "")
        ) if recruiters else ""

        # Nobody inside — try Hunter for a product leader (fresh, strong roles
        # only, capped per run), else hand over a search link.
        row["fallback_contact"] = ""
        if not people:
            lead = None
            fresh = (hours_old(job.get("posted_at", "")) or 1e9) <= HUNTER_COLD_MAX_AGE_H
            if (hunter_budget > 0 and fresh and not PREVIEW_MODE
                    and float(job.get("score", 0) or 0) >= HUNTER_COLD_MIN_SCORE):
                hunter_budget -= 1
                lead = hunter_product_leader(company)
            if lead:
                row["fallback_contact"] = sheets.hyperlink(
                    f"mailto:{lead['email']}", f"{lead['name']} — {lead.get('position','')[:40]}"
                )
                row["notes"] = (f"Hunter: {lead['name']}, {lead.get('position','')[:50]} "
                                f"(confidence {lead.get('confidence',0)}%). " + row["notes"])[:300]
                counters["hunter cold lead"] += 1
            else:
                row["fallback_contact"] = sheets.hyperlink(
                    people_search_url(company), f"Find someone at {company}"
                )

        rows.append(row)
        if people:
            counters[f"{len(people[:PEOPLE_SLOTS])} referrer(s)"] += 1
        else:
            counters["no contact — search link"] += 1
        if recruiters:
            counters["recruiter found"] += 1

    print(f"\n  {len(rows)} role(s) prepared")
    for label, n in counters.most_common():
        print(f"    {label:<34} {n}")

    if PREVIEW_MODE:
        print(f"\n  --preview {PREVIEW_N} — nothing written:\n")
        for r in rows[:PREVIEW_N]:
            warm = "warm" if r["first_degree_available"] == "TRUE" else "cold"
            print(f"    [{warm}] {r['title'][:44]} @ {r['company']}")
            for slot in (1, 2):
                if r[f"referrer_{slot}"]:
                    print(f"        referrer_{slot}: "
                          f"{_label(r[f'referrer_{slot}'])} ({r[f'referrer_{slot}_owner']})")
            if r["recruiter"]:
                print(f"        recruiter:  {_label(r['recruiter'])}")
            if r["fallback_contact"]:
                print(f"        fallback:   search link")
        return

    ws = sheets.get_referrals_tab()
    added = sheets.append_rows_dedup(ws, rows, sheets.REFERRALS_COLUMNS, "job_id")
    print(f"\n  Wrote {added} new role(s) to the Referrals tab.")
    print("  Rows already there were left alone — nothing you have edited is lost.")


def _label(formula: str) -> str:
    """Pulls the display text back out of a =HYPERLINK() cell for printing."""
    if formula.startswith("=HYPERLINK("):
        parts = formula.split('","')
        if len(parts) == 2:
            return parts[1].rstrip('")')
    return formula


if __name__ == "__main__":
    main()
