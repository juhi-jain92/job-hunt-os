"""
contact_extract.py — Finds named humans from public company sources.

This is the primary route for cold outreach, not the fallback. LinkedIn
connection requests are capped at 15/week against a volume target near 60,
so most reach has to come from channels that don't consume the cap: a public
team page, a Greenhouse board, and an email pattern.

Sources, in order of reliability:
  1. Greenhouse board  — open roles by department. Not humans, but a dated,
     verifiable signal of where a company is investing right now.
  2. Public team/about page — named humans with titles. Best-effort HTML
     parsing; brittle by nature, so everything is reported with a confidence
     and nothing is written to the sheet without a human confirming.
  3. Hunter.io domain search — the company's email pattern, so a name found
     in (2) becomes a reachable address. Needs HUNTER_API_KEY in .env.

Never touches LinkedIn. Fetches one page per company, politely.

Usage:
    python3 contact_extract.py --company moloco
    python3 contact_extract.py --company moloco --team-url https://moloco.com/team
    python3 contact_extract.py --company moloco --domain moloco.com
"""

import os
import re
import sys
import time
from html.parser import HTMLParser

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

HUNTER_API_KEY = os.getenv("HUNTER_API_KEY")

GREENHOUSE_JOBS  = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
GREENHOUSE_DEPTS = "https://boards-api.greenhouse.io/v1/boards/{slug}/departments"
HUNTER_DOMAIN    = "https://api.hunter.io/v2/domain-search"

USER_AGENT = "Mozilla/5.0 (compatible; job-hunt-os/1.0; personal job search)"
TIMEOUT    = 15

# A title has to name a role, not just a topic. Matching bare "product" lets
# a "Products" nav link pass as somebody's job.
ROLE_RE = re.compile(
    r"\b(manager|director|head of|vp|vice president|chief|founder|co-founder"
    r"|officer|president|lead|general manager|gm|partner|principal)\b",
    re.IGNORECASE,
)

# Two-to-three capitalized words, allowing O'Brien / Al-Rashid / de Souza.
NAME_RE = re.compile(
    r"^(?:[A-Z][a-z'’\-]+|[A-Z]\.)"
    r"(?:\s+(?:de|van|von|del|da|di|bin|al))?"
    r"(?:\s+(?:[A-Z][a-zA-Z'’\-]+|[A-Z]\.)){1,2}$"
)

# Marketing pages are full of two-capitalized-word phrases that look exactly
# like names ("Meet Claude", "Try Sonnet"). Anything opening with one of these
# is a call to action, not a person.
NAV_OPENERS = {
    "meet", "try", "see", "get", "join", "read", "view", "learn", "start",
    "explore", "contact", "about", "our", "the", "why", "how", "what", "all",
    "book", "watch", "download", "request", "build", "discover", "sign",
    "log", "create", "find", "talk", "chat", "ask", "privacy", "terms",
    "cookie", "back", "next", "more", "new", "introducing", "announcing",
}


def _flag(name: str, default=None):
    if name not in sys.argv:
        return default
    try:
        value = sys.argv[sys.argv.index(name) + 1]
        return default if value.startswith("--") else value
    except IndexError:
        return default


class _TextExtractor(HTMLParser):
    """Collects visible text nodes in document order, skipping script/style."""

    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self.chunks.append(text)


def fetch_greenhouse_signal(slug: str) -> dict:
    """
    Open roles by department — where the company is investing right now, and
    the closest thing to a product-line map available without paid data.

    The /jobs response carries no department field, so this uses the separate
    /departments endpoint.
    """
    try:
        resp = requests.get(
            GREENHOUSE_DEPTS.format(slug=slug),
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        if resp.status_code == 404:
            return {"available": False, "reason": "not on Greenhouse"}
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"available": False, "reason": str(e)[:80]}

    departments = [
        (d.get("name", ""), len(d.get("jobs", []) or []))
        for d in resp.json().get("departments", [])
        if d.get("name")
    ]
    staffed = sorted(
        [(n, c) for n, c in departments if c > 0], key=lambda x: -x[1]
    )

    return {
        "available": True,
        "open_roles": sum(c for _, c in staffed),
        "by_department": staffed[:8],
        # Deliberately wide — callers filter these down to product-adjacent
        # orgs, and the largest department is often a sales team.
        "product_lines": [n for n, _ in staffed[:12]],
    }


def fetch_team_page(url: str) -> list:
    """
    Best-effort extraction of name/title pairs from a public team page.

    Pairs a name-shaped text node with the node that follows it, which is how
    nearly every team page is laid out. Returns candidates, not facts —
    confirm before using.
    """
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"    [team page] fetch failed: {str(e)[:90]}", file=sys.stderr)
        return []

    parser = _TextExtractor()
    parser.feed(resp.text)
    chunks = parser.chunks

    found, seen = [], set()
    for i, text in enumerate(chunks):
        if len(text) > 40 or text in seen or not NAME_RE.match(text):
            continue
        if text.split()[0].lower() in NAV_OPENERS:
            continue
        if i + 1 >= len(chunks):
            continue

        # The very next node must read as a job title. A window would let any
        # nearby footer text vouch for a phrase that is not a person.
        title = chunks[i + 1]
        if not (3 < len(title) <= 90):
            continue
        if not ROLE_RE.search(title):
            continue
        if title.lower().split()[0] in NAV_OPENERS:
            continue

        seen.add(text)
        found.append({
            "name": text,
            "title": title,
            "source": url,
            "confidence": "unconfirmed",
        })

    return found


def hunter_domain_search(domain: str = "", company: str = "") -> dict:
    """
    The company's email pattern plus any public addresses Hunter has indexed.
    Accepts a domain or, when none is known, a company name (Hunter resolves it).
    """
    if not HUNTER_API_KEY:
        return {
            "available": False,
            "reason": "HUNTER_API_KEY not set in .env — add it to enable email lookup",
        }

    try:
        resp = requests.get(
            HUNTER_DOMAIN,
            params={**({"domain": domain} if domain else {"company": company}),
                    "api_key": HUNTER_API_KEY, "limit": 10},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"available": False, "reason": str(e)[:90]}

    data = resp.json().get("data", {})
    return {
        "available": True,
        "pattern": data.get("pattern", ""),
        "emails": [
            {
                "email": e.get("value", ""),
                "name": f"{e.get('first_name','')} {e.get('last_name','')}".strip(),
                "position": e.get("position", "") or "",
                "confidence": e.get("confidence", 0) or 0,
            }
            for e in data.get("emails", [])
            if e.get("value")
        ],
    }


HUNTER_VERIFY = "https://api.hunter.io/v2/email-verifier"
CONFIDENCE_TRUSTED = 80  # indexed emails at/above this skip the verifier


def hunter_verify(email: str) -> dict:
    """
    One verification credit (100/month on the free plan), so callers only
    verify guessed or low-confidence addresses — never the whole queue.
    Returns {"status": valid|accept_all|unknown|invalid|unavailable, "score": int}.
    """
    if not HUNTER_API_KEY or not email:
        return {"status": "unavailable", "score": 0}
    try:
        resp = requests.get(
            HUNTER_VERIFY,
            params={"email": email, "api_key": HUNTER_API_KEY},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        d = resp.json().get("data", {})
        return {"status": d.get("status", "unknown"), "score": d.get("score", 0)}
    except requests.RequestException:
        # Out of credits or transient failure — treat as unknown, never block.
        return {"status": "unavailable", "score": 0}


def apply_pattern(pattern: str, first: str, last: str, domain: str) -> str:
    """Hunter returns patterns like '{first}.{last}'. Fills one in."""
    if not pattern or not first:
        return ""
    local = (pattern
             .replace("{first}", first.lower())
             .replace("{last}", last.lower())
             .replace("{f}", first[:1].lower())
             .replace("{l}", last[:1].lower() if last else ""))
    return f"{local}@{domain}" if "{" not in local else ""


def extract(company: str, slug: str = None, team_url: str = None, domain: str = None) -> dict:
    """Everything findable about one company from public sources."""
    slug = slug or company.lower().replace(" ", "")
    result = {"company": company, "slug": slug, "people": []}

    print(f"    Greenhouse board ...")
    result["greenhouse"] = fetch_greenhouse_signal(slug)
    gh = result["greenhouse"]
    if gh.get("available"):
        depts = ", ".join(f"{n} ({c})" for n, c in gh["by_department"][:4])
        print(f"      {gh['open_roles']} open roles — {depts or 'no departments listed'}")
    else:
        print(f"      unavailable ({gh.get('reason')})")

    if team_url:
        print(f"    Team page ...")
        people = fetch_team_page(team_url)
        result["people"] = people
        print(f"      {len(people)} candidate(s) found")
    else:
        print(f"    Team page — skipped (pass --team-url to enable)")

    if domain:
        print(f"    Hunter.io ...")
        hunter = hunter_domain_search(domain)
        result["hunter"] = hunter
        if hunter.get("available"):
            print(f"      pattern: {hunter['pattern'] or '(none)'}"
                  f" · {len(hunter['emails'])} indexed address(es)")
            for person in result["people"]:
                parts = person["name"].split()
                if len(parts) >= 2:
                    person["email_guess"] = apply_pattern(
                        hunter["pattern"], parts[0], parts[-1], domain
                    )
        else:
            print(f"      unavailable ({hunter.get('reason')})")

    time.sleep(0.5)
    return result


def main():
    company = _flag("--company")
    if not company:
        sys.exit(
            "Usage: python3 contact_extract.py --company <name> "
            "[--slug X] [--team-url URL] [--domain example.com]"
        )

    print(f"\n  Extracting public contacts for {company}")
    print("  " + "-" * 54)
    result = extract(
        company,
        slug=_flag("--slug"),
        team_url=_flag("--team-url"),
        domain=_flag("--domain"),
    )

    if result["people"]:
        print(f"\n  Candidates — confirm each before using:")
        for p in result["people"]:
            line = f"    {p['name']:<26} {p['title'][:44]}"
            if p.get("email_guess"):
                line += f"\n      guess: {p['email_guess']}"
            print(line)
    else:
        print("\n  No named people extracted. Team pages that render via"
              "\n  JavaScript return nothing to a plain fetch — check the page"
              "\n  by hand, or fall back to the LinkedIn search link.")


if __name__ == "__main__":
    main()
