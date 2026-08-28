"""
networking_daily.py — Picks the day's outreach targets and queues prospects.

Five slots per day, where a slot is a company or one product line inside a big
one. You can't meaningfully "reach out to Databricks" — you reach out to a
specific org, and each needs its own observation. So a large company consumes
two or three slots and a small one consumes a single slot, which is the "fewer
companies if it's massive" rule expressed as arithmetic.

Size is read from the live Greenhouse board rather than a hand-maintained
file: open-role count is a free, current proxy for scale, and the department
breakdown is the closest thing to a product-line map available without paid
data.

Named humans come from public sources first — the Greenhouse board and, when
HUNTER_API_KEY is set, Hunter.io. LinkedIn search links are the fallback, not
the primary route, because connection requests are capped at 15/week and the
volume target is far above that.

Every row is written as PROSPECT with no name attached. You click, pick a
human, and type the name. Identification is queued by machine; selection stays
human, and nothing is ever sent.

Usage:
    python3 networking_daily.py --dry-run       show today's picks, write nothing
    python3 networking_daily.py                 queue them
    python3 networking_daily.py --slots 8       a bigger day
    python3 networking_daily.py --people 3      prospects per product line
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta

import sheets
from contact_extract import extract, hunter_domain_search
from linkedin_urls import people_search_url, research_links, school_search_url
from normalize import is_blocked, norm_company

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "config", "search_config.json")
TARGETS_PATH = os.path.join(BASE, "config", "target_companies.json")
META_PATH = os.path.join(BASE, "config", "company_meta.json")

_cfg = {}
try:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        _cfg = json.load(fh).get("velocity", {})
except (FileNotFoundError, json.JSONDecodeError):
    pass

DEFAULT_SLOTS = 5
COOLDOWN_DAYS = 14

# Open-role count → how many slots the company costs and how many product
# lines to target inside it.
SIZE_BANDS = [
    (300, "large",  3),
    (80,  "medium", 2),
    (0,   "small",  1),
]

SCHOOLS = ("Indian School of Business", "Delhi Technological University")

# Greenhouse department names are raw org labels, so the biggest one is often
# a sales or support org. Only these are worth a PM's outreach.
RELEVANT_LINE_TERMS = (
    "product", "ads", "advertis", "monetiz", "machine learning", "ml ",
    "ai", "data science", "platform", "growth", "measurement", "commerce",
    "media", "demand", "supply", "identity", "analytics", "core",
)

IRRELEVANT_LINE_TERMS = (
    "sales", "recruit", "people", "hr", "finance", "legal", "facilit",
    "workplace", "support", "success", "on site", "onsite", "shelter",
    "warehouse", "driver", "operations - ", "accounting", "payroll",
)


def relevant_lines(lines: list) -> list:
    """Keeps product-adjacent orgs, drops sales and back-office ones."""
    keep = []
    for line in lines:
        low = line.lower()
        if any(t in low for t in IRRELEVANT_LINE_TERMS):
            continue
        if any(t in low for t in RELEVANT_LINE_TERMS):
            keep.append(line)
    return keep


def _flag(name: str, default):
    if name not in sys.argv:
        return default
    try:
        return type(default)(sys.argv[sys.argv.index(name) + 1])
    except (IndexError, ValueError):
        return default


DRY_RUN   = "--dry-run" in sys.argv
SLOTS     = _flag("--slots", DEFAULT_SLOTS)
PER_LINE  = _flag("--people", 3)


def load_meta() -> dict:
    """Optional overrides: careers/team URL and email domain per company."""
    try:
        with open(META_PATH, encoding="utf-8") as fh:
            return {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_slugs() -> list:
    try:
        with open(TARGETS_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("greenhouse_slugs", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def load_manual_targets() -> list:
    """Pre-qualified companies (mostly not on Greenhouse) — see target_companies.json."""
    try:
        with open(TARGETS_PATH, encoding="utf-8") as fh:
            return json.load(fh).get("manual_targets", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def classify(open_roles: int) -> tuple:
    for floor, label, cost in SIZE_BANDS:
        if open_roles >= floor:
            return label, cost
    return "small", 1


def days_since(value: str):
    if not value:
        return None
    try:
        return (datetime.now() - datetime.strptime(value[:10], "%Y-%m-%d")).days
    except ValueError:
        return None


def build_pool(targets_rows: list, slugs: list) -> list:
    """
    Companies worth a touch today, best first.

    Anything recommended within the cooldown window is suppressed outright —
    without it the same three companies win every day.
    """
    pool = []
    seen = set()

    # Manual targets outrank everything: they are pre-qualified by research,
    # and most have no public board for the signal-based scoring below.
    for t in load_manual_targets():
        key = norm_company(t.get("company", ""))
        if not key or is_blocked(key):
            continue
        seen.add(key)
        cooldown = None
        for r in targets_rows:
            if r.get("company_norm") == key:
                cooldown = days_since(r.get("last_recommended_on", ""))
                break
        if cooldown is not None and cooldown < COOLDOWN_DAYS:
            continue
        pool.append({
            "company": t.get("company", ""), "company_norm": key,
            "slug": key.replace(" ", ""), "score": 10, "manual": True,
            "source": "manual_targets", "row_num": None,
        })

    for r in targets_rows:
        key = r.get("company_norm", "")
        if not key or key in seen or is_blocked(key):
            continue
        seen.add(key)

        cooldown = days_since(r.get("last_recommended_on", ""))
        if cooldown is not None and cooldown < COOLDOWN_DAYS:
            continue

        score = 0
        if r.get("best_tier") == "Tier 1":
            score += 3
        elif r.get("best_tier") == "Tier 2":
            score += 2
        try:
            score += 3 if int(r.get("first_degree_count") or 0) > 0 else 0
            score += 2 if int(r.get("dormant_count") or 0) > 0 else 0
        except ValueError:
            pass
        age = days_since((r.get("role_posted_at") or "")[:10])
        if age is not None and age <= 2:
            score += 3

        pool.append({
            "company": r.get("company_display") or key,
            "company_norm": key,
            "slug": key.replace(" ", ""),
            "score": score,
            "source": "targets",
            "row_num": r.get("_row_num"),
        })

    # Untouched companies from the curated list, so the pool never runs dry.
    for slug in slugs:
        key = norm_company(slug)
        if key in seen or is_blocked(key):
            continue
        pool.append({
            "company": slug.capitalize(),
            "company_norm": key,
            "slug": slug,
            "score": 1,
            "source": "target_companies",
            "row_num": None,
        })

    pool.sort(key=lambda c: -c["score"])
    return pool


def prospect_id(company: str, line: str, n: int) -> str:
    seed = f"{company}|{line}|{n}|{datetime.now().strftime('%Y-%m-%d')}"
    return "o_" + hashlib.sha1(seed.encode()).hexdigest()[:16]


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    meta = load_meta()

    targets_ws = sheets.get_targets_tab()
    targets_rows = sheets.get_all_rows_with_numbers(targets_ws)
    pool = build_pool(targets_rows, load_slugs())

    if not pool:
        sys.exit(
            "\nNothing eligible today — every known company is inside its "
            f"{COOLDOWN_DAYS}-day cooldown.\n"
            "  Run referral_match.py to add targets, or wait."
        )

    print(f"\n  {len(pool)} companies eligible. Filling {SLOTS} slot(s).\n")

    picks, used = [], 0
    for candidate in pool:
        if used >= SLOTS:
            break

        print(f"  {candidate['company']}")
        info = extract(
            candidate["company"],
            slug=candidate["slug"],
            team_url=meta.get(candidate["company_norm"], {}).get("team_url"),
            domain=meta.get(candidate["company_norm"], {}).get("domain"),
        )

        gh = info.get("greenhouse", {})
        if not gh.get("available"):
            if candidate.get("manual"):
                # Pre-qualified by research — no board needed. One slot,
                # company-wide, LinkedIn search links as the route.
                gh = {"available": True, "open_roles": 0, "product_lines": []}
            else:
                print(f"    skipped — no public board ({gh.get('reason')})\n")
                continue

        size, cost = classify(gh.get("open_roles", 0))
        if used + cost > SLOTS:
            print(f"    {size} company needs {cost} slots, only "
                  f"{SLOTS - used} left — skipping to a smaller one\n")
            continue

        if size == "small":
            lines = [""]
        else:
            lines = relevant_lines(gh.get("product_lines") or [])[:cost]
            if not lines:
                print("    no product-adjacent org on the board — "
                      "targeting company-wide\n")
                lines = [""]
                cost = 1
            elif len(lines) < cost:
                cost = len(lines)

        candidate.update({
            "size": size, "cost": cost, "lines": lines,
            "info": info, "open_roles": gh.get("open_roles", 0),
        })
        picks.append(candidate)
        used += cost
        print(f"    {size} · {gh.get('open_roles')} open roles · {cost} slot(s) · "
              f"targeting: {', '.join(l or 'company-wide' for l in lines)}\n")

    if not picks:
        sys.exit("  No company could be placed. Try --slots with a higher number.")

    rows = []
    for pick in picks:
        company = pick["company"]
        hunter = pick["info"].get("hunter", {})
        people = pick["info"].get("people", [])

        for line in pick["lines"]:
            label = f"{company} — {line}" if line else company
            title_filter = f'"{line}" ("Head of Product" OR "Director" OR "VP")' \
                if line else None

            for n in range(PER_LINE):
                # A named human from a public source beats a search link.
                named = people[n] if n < len(people) else None
                hunter_person = None
                if not named and hunter.get("available"):
                    pool_e = hunter.get("emails", [])
                    hunter_person = pool_e[n] if n < len(pool_e) else None

                if named:
                    link, note = named.get("source", ""), \
                        f"From public team page: {named['title'][:60]}. Confirm before sending."
                    name = named["name"]
                elif hunter_person:
                    link = f"mailto:{hunter_person['email']}"
                    name = hunter_person["name"]
                    note = f"From Hunter.io: {hunter_person['position'][:60]}. Verify the role is current."
                else:
                    link = people_search_url(company, title_filter) if title_filter \
                        else people_search_url(company)
                    name = ""
                    note = "No public name found — open the search link and pick someone."

                rows.append({
                    "outreach_id": prospect_id(company, line, n),
                    "due_date": today,
                    "priority": 3,
                    "status": "PROSPECT",
                    "contact_name": name,
                    "company_display": label,
                    "role_title": "",
                    "channel": "email" if name and hunter_person else "linkedin_connect_note",
                    "message_shape": "cold_email" if hunter_person else "stranger_no_ask",
                    "owner": "juhi",
                    "link": link,
                    "company_norm": pick["company_norm"],
                    "generated_at": today,
                    "notes": note,
                })

            # One alumni route per line — the warmest cold path available.
            rows.append({
                "outreach_id": prospect_id(company, line, 99),
                "due_date": today,
                "priority": 2,
                "status": "PROSPECT",
                "contact_name": "",
                "company_display": label,
                "channel": "linkedin_connect_note",
                "message_shape": "stranger_no_ask",
                "owner": "juhi",
                "link": school_search_url(company, SCHOOLS[0]),
                "company_norm": pick["company_norm"],
                "generated_at": today,
                "notes": f"{SCHOOLS[0]} alumni at {company} — warmest cold route.",
            })

    named_count = sum(1 for r in rows if r["contact_name"])
    print("  " + "=" * 54)
    print(f"  {len(picks)} companies · {used}/{SLOTS} slots · {len(rows)} prospects")
    print(f"  {named_count} with a name attached, "
          f"{len(rows) - named_count} as search links")
    print("  " + "=" * 54)

    if DRY_RUN:
        print("\n  --dry-run — nothing written.\n")
        for r in rows[:20]:
            who = r["contact_name"] or "(pick one)"
            print(f"    {who:<24} {r['company_display'][:38]}")
            print(f"      {r['link'][:96]}")
        return

    outreach_ws = sheets.get_networking_tab()
    added = sheets.append_rows_dedup(
        outreach_ws, rows, sheets.NETWORKING_COLUMNS, "outreach_id"
    )

    stamps = [
        {"row_num": p["row_num"], "values": {"last_recommended_on": today}}
        for p in picks if p.get("row_num")
    ]
    if stamps:
        sheets.batch_update_cells(targets_ws, stamps, sheets.TARGETS_COLUMNS)

    print(f"\n  Queued {added} prospect(s). Nothing is sent — open the Outreach"
          "\n  tab, click through, and put names to the rows you want.")


if __name__ == "__main__":
    main()
