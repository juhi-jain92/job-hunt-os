"""
draft_notes.py — Writes the day's outreach drafts into the sheet.

The one stage that turns a match into something sendable. Picks at most N
undrafted rows (warm referrals first, then named networking prospects), does a
short web search for a fresh company-specific hook, chooses one story from the
story bank with rotation, and writes a 4-bullet note. Everything is validated
in Python before it touches the sheet: a hook is required, a verbatim metric
is required, length is enforced. Status is never changed. Nothing is sent.

Runs in the cloud (Sonnet 5 + web search, ~5-8 cents a draft) so drafts exist
every morning whether or not any app is open.

Usage:
    python3 draft_notes.py --preview        pick rows, print drafts, write nothing
    python3 draft_notes.py                  draft up to 5 and write them
    python3 draft_notes.py --n 3            per lane
    python3 draft_notes.py --refresh-digest rebuild config/story_digest.json from
                                            resume/story-bank.md (local only)
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta

import anthropic
from dotenv import load_dotenv

import sheets

load_dotenv()
BASE = os.path.dirname(__file__)
API_KEY = os.getenv("ANTHROPIC_API_KEY")

_cfg = json.load(open(os.path.join(BASE, "config", "search_config.json")))
_out = _cfg.get("outreach_settings", {})
MODEL  = _out.get("model", "claude-sonnet-5")
EFFORT = _out.get("effort", "high")

STORY_BANK   = os.path.join(BASE, "resume", "story-bank.md")
STORY_DIGEST = os.path.join(BASE, "config", "story_digest.json")
ROTATION_DAYS = 7
MAX_WORDS = 280          # email / DM
MAX_CHARS_CONNECT = 280  # LinkedIn connection request

PREVIEW = "--preview" in sys.argv
N = 5
if "--n" in sys.argv:
    try:
        N = int(sys.argv[sys.argv.index("--n") + 1])
    except (IndexError, ValueError):
        pass


# ── Story bank ───────────────────────────────────────────────────────────────

def build_digest() -> list:
    """
    Compacts resume/story-bank.md into what a draft needs: id, title, tags,
    impact line, earned secret. The full bank is personal and gitignored; the
    digest is committed so cloud runs can draft.
    """
    text = open(STORY_BANK, encoding="utf-8").read()
    entries = re.split(r"\n(?=### S\d{3} · )", text)
    digest = []
    for e in entries:
        # Tags may be followed by a suffix ("(best influence story)", "— DRAFT"),
        # so pull them from anywhere on the heading and take the title as
        # everything before the first tag.
        head = e.split("\n")[0]
        m = re.match(r"### (S\d{3}) · (.*)$", head)
        if not m:
            continue
        sid, rest = m.group(1), m.group(2)
        tags  = re.findall(r"\[([^\]]+)\]", rest)
        title = re.split(r"\s*\[", rest, maxsplit=1)[0].strip(" —-")
        impact  = re.search(r"^\| Impact \| (.+?) \|$", e, re.M)
        secrets = re.findall(r"^Earned secret[^:]*: (.+)$", e, re.M)
        digest.append({
            "id": sid, "title": title, "tags": tags,
            "impact": impact.group(1).strip() if impact else "",
            "earned_secret": " / ".join(s.strip() for s in secrets)[:600],
        })
    return digest


def load_digest() -> list:
    if "--refresh-digest" in sys.argv or (not os.path.exists(STORY_DIGEST) and os.path.exists(STORY_BANK)):
        d = build_digest()
        json.dump(d, open(STORY_DIGEST, "w"), indent=2)
        print(f"  story digest: {len(d)} stories → config/story_digest.json")
    try:
        return json.load(open(STORY_DIGEST))
    except FileNotFoundError:
        sys.exit(f"  [FATAL] {STORY_DIGEST} missing and resume/story-bank.md not "
                 "available. Run locally: python3 draft_notes.py --refresh-digest, "
                 "then commit config/story_digest.json.")


# ── Row selection ─────────────────────────────────────────────────────────────

def blank(v) -> bool:
    return not (v or "").strip()


def pick_rows(n: int):
    """Warm referrals by score, then named networking prospects. Undrafted only."""
    ref_ws = sheets.get_referrals_tab()
    net_ws = sheets.get_networking_tab()
    # formulas=True so referrer_1 / fallback_contact arrive as the raw
    # =HYPERLINK(...) cell, which is where the mailto: lives. Without it the
    # cold-email lane in target_brief() can never match on "@".
    ref = sheets.get_all_rows_with_numbers(ref_ws, formulas=True)
    net = sheets.get_all_rows_with_numbers(net_ws)

    def score(r):
        try:
            return float(r.get("score", 0) or 0)
        except ValueError:
            return 0

    ref_c = [r for r in ref
             if blank(r.get("note_to_send")) and (r.get("stale", "") or "").upper() != "TRUE"
             and not any((r.get(k, "") or "").strip() for k in ("sent_1", "sent_2", "sent_rec"))]
    ref_c.sort(key=lambda r: (r.get("first_degree_available") != "TRUE", -score(r), r.get("posted_at", "")), reverse=False)

    net_c = [r for r in net
             if blank(r.get("draft_body")) and (r.get("contact_name", "") or "").strip()
             and (r.get("status", "") or "").upper() == "PROSPECT"]
    net_c.sort(key=lambda r: (r.get("priority", "9"), r.get("due_date", "")))

    # n per lane: the referral block and the networking block are separate
    # 20-minute sessions, so one lane must never starve the other.
    picks = [("referral", r) for r in ref_c[:n]] + [("networking", r) for r in net_c[:n]]
    used_recently = recent_story_ids(ref + net)
    return picks, ref_ws, net_ws, used_recently


def recent_story_ids(rows) -> set:
    cutoff = (datetime.now() - timedelta(days=ROTATION_DAYS)).strftime("%Y-%m-%d")
    return {r.get("story_id", "") for r in rows
            if (r.get("story_id", "") or "").strip() and (r.get("drafted_on", "") or "") >= cutoff}


# ── Drafting ──────────────────────────────────────────────────────────────────

RECIPE = """
You write ONE outreach note for Juhi Jain, an AI-native product leader (~10 yrs;
programmatic advertising, CTV, applied AI). She sends every note herself after
personalizing the last 10%. You never send anything.

Research first: use web search (2-3 searches max) for the company's product and
one FRESH, SPECIFIC fact — a launch, funding, partnership, controversy — and the
problem behind it. A note that could have been written last year convinces no one.

Then pick exactly ONE story from the STORY BANK below whose earned secret speaks
to that problem. Do not pick a story listed under DO NOT USE (rotation).

Return ONLY JSON, no fences:
{
  "story_id": "S0xx",
  "hook": "<the one fresh, specific observation about them, one sentence>",
  "note": "<4 short bullets, each starting with '• ', in this order:
           their product (proves understanding) / the fresh observation /
           her matching story in one line with ONE metric copied verbatim from
           the story's impact line / the ask: excited to be considered for a
           product role, or a 15-minute conversation>"
}

Hard rules: metrics verbatim from the impact line only, never invented or rounded.
Never claim production coding, LLM fine-tuning, RAG hands-on, or seniority above
Associate Director. Warm referral asks are short and specific; connection
requests (channel linkedin_connect_note) must be under 280 characters total.
""".strip()


def key_details() -> str:
    # Reuse the scorer's distilled resume so there is one source of truth.
    import match_scorer  # import-safe: main() is guarded
    return match_scorer.KEY_DETAILS


def system_blocks(digest: list) -> list:
    stories = "\n".join(
        f"{s['id']} · {s['title']} {' '.join('['+t+']' for t in s['tags'])}\n"
        f"   impact: {s['impact']}\n   earned secret: {s['earned_secret']}"
        for s in digest
    )
    return [{
        "type": "text",
        "text": f"{RECIPE}\n\n--- JUHI, KEY DETAILS ---\n{key_details()}\n\n--- STORY BANK ---\n{stories}",
        "cache_control": {"type": "ephemeral"},
    }]


def target_brief(lane: str, r: dict) -> str:
    if lane == "referral":
        unlink = lambda cell: re.sub(r'^=HYPERLINK\("[^"]*","(.*)"\)$', r"\1", cell or "")
        who = unlink(r.get("referrer_1", ""))
        cold = unlink(r.get("fallback_contact", ""))
        if who:
            lane_desc, contact, channel = "warm referral ask", who, "linkedin_dm"
        elif cold and "@" in (r.get("fallback_contact", "") or ""):
            lane_desc, contact, channel = "cold email to a product leader", cold, "email"
        else:
            lane_desc, contact, channel = "hiring-manager note", "unknown — write for the hiring manager", "linkedin_dm"
        return (f"LANE: {lane_desc}\nCOMPANY: {r.get('company','')}\n"
                f"ROLE: {r.get('title','')} (score {r.get('score','')})\n"
                f"CONTACT: {contact}\nCHANNEL: {channel}\n"
                f"SCORER NOTES: {(r.get('notes','') or '')[:300]}")
    return (f"LANE: cold networking\nCOMPANY: {r.get('company_display','')}\n"
            f"CONTACT: {r.get('contact_name','')} — {(r.get('notes','') or '')[:120]}\n"
            f"CHANNEL: {r.get('channel','')}\nJOB OPEN: {r.get('job_open','N')}")


def call_model(client, blocks, brief: str, banned: set) -> dict:
    user = brief + ("\n\nDO NOT USE (rotation): " + ", ".join(sorted(banned)) if banned else "")
    msg = client.messages.create(
        model=MODEL, max_tokens=4000, system=blocks,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": EFFORT},
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
        timeout=120,
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in response")
    return json.loads(m.group(0))


def validate(d: dict, digest: list, channel: str, banned: set) -> str:
    """Returns '' if the draft passes, else the reason."""
    ids = {s["id"]: s for s in digest}
    if d.get("story_id") not in ids:
        return "unknown story_id"
    if d["story_id"] in banned:
        return "story used within rotation window"
    hook = (d.get("hook") or "").strip()
    note = (d.get("note") or "").strip()
    if len(hook) < 20:
        return "hook missing"
    if note.count("•") < 3:
        return "fewer than 3 bullets"
    if channel == "linkedin_connect_note" and len(note) > MAX_CHARS_CONNECT:
        return f"connection note {len(note)} chars > {MAX_CHARS_CONNECT}"
    if len(note.split()) > MAX_WORDS:
        return f"{len(note.split())} words > {MAX_WORDS}"
    impact = ids[d["story_id"]]["impact"]
    # A bare digit ("5") is not a metric. Require a currency, percent, or
    # magnitude marker, or at least two characters, so "$4 to $1" and "50%"
    # count and a stray "1" in prose does not.
    nums = {n for n in re.findall(r"\$?\d[\d,.]*[%KMx+]*", impact)
            if len(n) > 1 or re.search(r"[$%KMx]", n)}
    if nums and not any(n in note for n in nums):
        return "no verbatim metric from the story's impact line"
    return ""


def main():
    if not API_KEY:
        sys.exit("ERROR: ANTHROPIC_API_KEY not set.")
    client = anthropic.Anthropic(api_key=API_KEY)
    digest = load_digest()
    picks, ref_ws, net_ws, banned = pick_rows(N)
    if not picks:
        print("  Nothing to draft — every eligible row already has a note.")
        return
    print(f"  Drafting {len(picks)} note(s) · rotation excludes {sorted(banned) or 'none'}")

    blocks = system_blocks(digest)
    today = datetime.now().strftime("%Y-%m-%d")
    ref_updates, net_updates, cost_notes = [], [], 0

    for lane, r in picks:
        label = r.get("company") or r.get("company_display")
        channel = r.get("channel", "linkedin_dm") if lane == "networking" else "linkedin_dm"
        brief = target_brief(lane, r)
        draft, why = None, "no attempt"
        for attempt in (1, 2):
            try:
                cand = call_model(client, blocks, brief, banned)
                why = validate(cand, digest, channel, banned)
                if not why:
                    draft = cand
                    break
                print(f"    [{label}] attempt {attempt} rejected: {why}")
            except (ValueError, json.JSONDecodeError, anthropic.APIError) as e:
                why = str(e)[:80]
                print(f"    [{label}] attempt {attempt} failed: {why}")
        if not draft:
            print(f"  ✗ {label}: no valid draft ({why}) — left blank for a human")
            continue

        banned.add(draft["story_id"])
        print(f"  ✓ {label} · {draft['story_id']} · hook: {draft['hook'][:70]}")
        if PREVIEW:
            print("    " + draft["note"].replace("\n", "\n    ") + "\n")
            continue
        # Written immediately: a hang or crash later must never lose a
        # draft that already passed validation.
        if lane == "referral":
            sheets.batch_update_cells(ref_ws, [{"row_num": r["_row_num"], "values": {
                "note_to_send": draft["note"], "story_id": draft["story_id"], "drafted_on": today}}],
                sheets.REFERRALS_COLUMNS)
            ref_updates.append(r["_row_num"])
        else:
            sheets.batch_update_cells(net_ws, [{"row_num": r["_row_num"], "values": {
                "draft_body": draft["note"], "personalization_hook": draft["hook"],
                "story_id": draft["story_id"], "drafted_on": today}}],
                sheets.NETWORKING_COLUMNS)
            net_updates.append(r["_row_num"])

    if PREVIEW:
        print("  --preview — nothing written.")
        return
    print(f"  Wrote {len(ref_updates)} referral + {len(net_updates)} networking draft(s). Nothing sent.")


if __name__ == "__main__":
    main()
