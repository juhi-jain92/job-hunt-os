"""
normalize.py — Company-name normalization and matching for the referral engine.

Joins LinkedIn "Company" values against job-board company names. These never
match exactly ("Google" vs "Google LLC" vs "Alphabet"), so matching runs in
four stages of decreasing confidence. The confidence label travels with the
match so callers can route low-confidence hits to human review.

Pure functions, stdlib only.
"""

import difflib
import json
import os
import re
import unicodedata

BASE = os.path.dirname(__file__)
ALIAS_PATH = os.path.join(BASE, "config", "company_aliases.json")

# Dropped during normalization — legal-entity noise, never meaning.
LEGAL_SUFFIXES = {
    "inc", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "gmbh", "pvt", "private", "ag", "bv", "nv", "sa", "srl", "ab",
    "oy", "kk", "llp", "lp", "the", "holdings", "holding",
}

# Too generic to carry a match on their own. "Scale AI" must not match
# "Anywhere AI" just because both end in "ai".
GENERIC_TOKENS = {
    "ai", "ml", "labs", "lab", "media", "digital", "data", "cloud", "health",
    "tech", "technologies", "technology", "systems", "group", "global",
    "network", "networks", "platform", "platforms", "solutions", "services",
    "software", "studio", "studios", "works", "partners", "ventures",
}


def _load_aliases() -> dict:
    try:
        with open(ALIAS_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
        return {k.lower(): v.lower() for k, v in raw.items() if not k.startswith("_")}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


ALIASES = _load_aliases()


def norm_company(raw: str) -> str:
    """
    Normalizes a company name for joining.

    Deliberately does NOT strip descriptive words like "technologies", "labs",
    or "ai" — stripping them turns "Scale AI" into "scale" and "Labelbox" into
    "box". Those collapses belong in company_aliases.json where they are
    explicit and reviewable.
    """
    s = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.split(r"\s+[-|–—]\s+", s)[0]      # "Google - Cloud" → "google"
    s = re.sub(r"\(.*?\)", " ", s)           # drop parentheticals
    s = re.sub(r"[^a-z0-9\s&]", " ", s)
    tokens = [t for t in s.split() if t not in LEGAL_SUFFIXES]
    normed = " ".join(tokens).strip()
    return ALIASES.get(normed, normed)


def _distinctive(tokens: set) -> bool:
    """True if the token set carries at least one non-generic word of real length."""
    return any(len(t) >= 4 and t not in GENERIC_TOKENS for t in tokens)


def match_company(a_raw: str, b_raw: str):
    """
    Returns a confidence label if the two names refer to the same company,
    else None.

    "alias"  — one side resolved through company_aliases.json
    "exact"  — identical after normalization
    "subset" — one token set contains the other, anchored on a distinctive word
    "fuzzy"  — high character similarity; callers must route these to review
    """
    a_norm_raw = re.sub(r"[^a-z0-9\s&]", " ", (a_raw or "").lower()).strip()
    b_norm_raw = re.sub(r"[^a-z0-9\s&]", " ", (b_raw or "").lower()).strip()

    a = norm_company(a_raw)
    b = norm_company(b_raw)
    if not a or not b:
        return None

    if a == b:
        # An alias fired if either side changed meaning during normalization.
        aliased = ALIASES.get(a_norm_raw) or ALIASES.get(b_norm_raw)
        return "alias" if aliased else "exact"

    ta, tb = set(a.split()), set(b.split())
    shorter = ta if len(ta) <= len(tb) else tb
    # Cap the extra-token gap at one: "Hightouch" ⊂ "Hightouch Data" is the same
    # company, but "Stripe" ⊂ "Stripe Payments International Holdings" is a guess.
    if (ta <= tb or tb <= ta) and abs(len(ta) - len(tb)) <= 1 and _distinctive(shorter):
        return "subset"

    # Length guard keeps "stripe" from matching a much longer entity name.
    if abs(len(a) - len(b)) <= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.90:
        return "fuzzy"

    return None


DIRECTOR_PLUS = ("director", "vp", "vice president", "head of", "partner", "principal")
MANAGER_TERMS = ("manager", "lead", "supervisor")
EXEC_TERMS    = ("chief", "founder", "ceo", "cto", "cpo", "coo", "cmo", "president")


def _has_term(text: str, term: str) -> bool:
    """Whole-word match — plain `in` makes 'director' contain 'cto'."""
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def seniority_hint(title: str) -> str:
    """Coarse seniority bucket from a LinkedIn position string."""
    t = (title or "").lower()
    if not t:
        return "unknown"
    if "recruit" in t or "talent acquisition" in t or "sourcer" in t:
        return "recruiter"
    if any(_has_term(t, term) for term in EXEC_TERMS):
        return "exec"
    if any(_has_term(t, term) for term in DIRECTOR_PLUS):
        return "director+"
    if any(_has_term(t, term) for term in MANAGER_TERMS):
        return "manager"
    return "ic"


# ── Company blocklist ─────────────────────────────────────────────────────────

import json as _json
import os as _os

_TARGETS = _os.path.join(_os.path.dirname(__file__), "config", "target_companies.json")

def _blocked() -> set:
    try:
        raw = _json.load(open(_TARGETS)).get("blocked_companies", [])
    except (FileNotFoundError, _json.JSONDecodeError):
        raw = []
    return {norm_company(c) for c in raw if c}

BLOCKED = _blocked()


def is_blocked(company: str) -> bool:
    """True for companies Juhi never wants surfaced, matched on normalized name."""
    return norm_company(company) in BLOCKED
