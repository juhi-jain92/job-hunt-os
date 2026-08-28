"""
match_scorer.py — Reads every unscored job from the "Job Hunt OS" sheet,
calls Claude once per job to score it against the AI and adtech tracks using
the eval framework rubric, then batch-writes all scores back to the sheet.
"""

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Optional

import anthropic
from dotenv import load_dotenv

import sheets

# ── 1. Config & secrets ──────────────────────────────────────────────────────

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_key_here":
    sys.exit("ERROR: Set ANTHROPIC_API_KEY in your .env file. Get it at console.anthropic.com → API Keys.")

BASE = os.path.dirname(__file__)

# Statuses the user owns — scorer never touches these rows
USER_OWNED_STATUSES = {"applied", "interviewing", "rejected", "skipped"}

# Delay between Claude calls to stay well inside rate limits
CALL_DELAY_SECONDS = 0.1

# ── 2. Load context files ────────────────────────────────────────────────────

def _load(path: str, label: str) -> str:
    full = os.path.join(BASE, path)
    if os.path.exists(full):
        return open(full).read().strip()
    print(f"  [warning] {label} not found at {path} — continuing without it.", file=sys.stderr)
    return ""

context_store  = json.loads(open(os.path.join(BASE, "config", "context_store.json")).read())
_search_config = json.loads(open(os.path.join(BASE, "config", "search_config.json")).read())
_scorer_cfg    = _search_config.get("scorer_settings", {})
MODEL          = _scorer_cfg.get("model",  "claude-sonnet-5")
EFFORT         = _scorer_cfg.get("effort", "low")
rubric_text      = _load("config/job_fit_eval_framework.md", "eval framework")
resume_ai        = _load("resume/resume_ai.md",              "AI resume")
resume_adtech    = _load("resume/resume_adtech.md",          "Adtech resume")

# Guardrails: load from file if it exists, otherwise use inline version
_guardrails_file = _load("guardrails/guardrails.md", "guardrails file")
GUARDRAILS = _guardrails_file if _guardrails_file else """
You are a precise, honest job-fit scorer. Apply these rules without exception:

ACCURACY
- Never add skills, titles, or experience not explicitly in the candidate's resume
- Never exaggerate metrics — exact numbers only, traceable to the experience library
- Never claim a seniority level higher than Associate Director
- Score honestly; do not inflate scores to flatter

HARD LIMITS (cannot claim)
- Production Python/TypeScript code, LLM fine-tuning, RAG pipeline hands-on, vector database implementation
- The chatbot at LG Ads was a Type-1 deterministic read-only diagnostic agent, NOT a probabilistic RAG chatbot
- Job Hunt OS and Creative Approval Workflow are personal portfolio projects built with Claude Code, not shipped commercial products — cannot claim production deployment at scale, user base, or revenue
- Can claim: agentic workflow design, LLM orchestration, prompt engineering, guardrails design, eval framework design

SCORING BEHAVIOR
- If the JD requires something the candidate clearly lacks, flag it explicitly in the reason field
- If match score confidence is low due to missing or thin JD content, say so explicitly in the reason field
- Score leniently on domain when AI readiness is high: a strong AI-core role in an adjacent domain (e.g. healthtech, fintech) is NOT an automatic skip — let ai_readiness_score carry the total if the AI fit is genuine
""".strip()

# Build a compact candidate profile string from context_store
_cand    = context_store["candidate"]
_shared  = context_store["shared"]
_tracks  = context_store["tracks"]
_company = context_store["company_profile"]

CANDIDATE_PROFILE = f"""
CANDIDATE: {_cand['name']}
YOE: {_cand['yoe']} years
Current status: {_cand['status']}
Location: {_cand['location']}
Locations OK: {', '.join(_shared['locations'])}
Remote preference: {_shared['remote_preference']}
Salary floor: ${_shared['salary']['tc_floor']:,} TC
Seniority band: {', '.join(_shared['seniority_band'])}
Company preference: {_company['stage']}
Avoid: {_company['avoid']}
Dream tier: {', '.join(_company['dream_tier'])}

AI TRACK positioning: {_tracks['ai']['positioning']}
AI TRACK must-have signals: {', '.join(_tracks['ai']['must_have_signals'])}
AI TRACK dealbreakers: {'; '.join(_tracks['ai']['dealbreakers'])}

ADTECH TRACK positioning: {_tracks['adtech']['positioning']}
ADTECH TRACK must-have signals: {', '.join(_tracks['adtech']['must_have_signals'])}
ADTECH TRACK dealbreakers: {'; '.join(_tracks['adtech']['dealbreakers'])}
""".strip()

RESUME_SECTION = """
--- RESUME VERSION B (AI / Builder track) — key skills & experience ---
- Associate Director, PM at LG Ads (~10 yrs PM total); seniority band Senior PM → AD
- AI workflows built: real-time creative scanning & approval ($18M projected), AI creative resizing (1 wk→1 min), campaign troubleshooting chatbot (50% ticket cut), Segment Portal AI agent (10% ops bandwidth freed)
- 0-to-1 platforms: River OS TV OS (100K TVs; voice recommender adopted by LGE on 100M+ TVs), programmatic home screen monetization ($16M ARR, first OEM in industry), Alt ID/identity infra ($3M rev, 3X bid rates, 60% CTV coverage), Supply Diagnostics Platform ($1.3M)
- ML systems: Inventory Quality ML (invalid traffic detection, $4M impact, 20% margin lift), supply-demand matching ($1M)
- Privacy/compliance: GDPR, CCPA, DNT/LMT — identified $6M EU GDPR gap, drove 60%+ opt-in
- Can claim: agentic workflow design, LLM orchestration, prompt engineering, guardrails design, eval framework design
- Cannot claim: production Python/TypeScript code, LLM fine-tuning, RAG pipeline, vector DBs
- Led/mentored 4 PMs + 6 solution engineers; ISB PGP Management; DeepLearning.AI certified

--- RESUME VERSION A (Adtech track) — key skills & experience ---
- Same person; emphasis on programmatic advertising, CTV, identity, and adtech platform expertise
- Owned $400M programmatic business: demand, supply, identity, monetization across CTV video and display
- Identity: UID2, RampID, Alt ID + 3 others, Google PAL, APS — 60% O&O CTV coverage, 3X bid rates
- Programmatic monetization: 0-to-1 home screen inventory; 10+ DSPs/SSPs/resellers onboarded; $16M ARR
- Ad server: inventory filtering, waterfall management, productionized maintenance suite
- Attribution: 0-to-1 offline attribution (IP-to-Household), Share of Voice reporting
- Privacy gatekeeper: GDPR, CCPA, DNT/LMT, DPAs — negotiated with Google, LG HQ, legal counsel
- Inventory quality: ML-based IVT detection ($4M), supply-demand matching ($1M), multi-tag calling ($1.2M)
- B2B partnerships: DSPs, SSPs, publishers, OEM (LG HQ); OOH/hotel/in-vehicle expansion POCs
- CTV/OTT: River OS, voice recommender (100M+ TVs), app partnerships (Prime, Hotstar, Zee5, SonyLiv)
""".strip()

# ── 3. Claude scoring ─────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

JSON_SCHEMA = """
Return ONLY a valid JSON object with exactly these keys. No markdown fences, no prose:

{
  "ai_score":           <int 0-3, AI Readiness dimension score>,
  "adtech_score":       <int 0-3, Adtech Domain fit score>,
  "domain_score":       <int 0-3, Domain Match rubric dimension>,
  "ai_readiness_score": <int 0-3, AI Readiness rubric dimension>,
  "skills_score":       <int 0-2, Skills Match rubric dimension>,
  "level_score":        <int 0-2, Level & Scope rubric dimension>,
  "total_score":        <int, domain_score + ai_readiness_score + skills_score + level_score>,
  "track":              <"AI" | "ADTECH" | "DUAL" | "LOW MATCH">,
  "tier":               <"Tier 1" | "Tier 2" | "Tier 3" | "Skip">,
  "hard_skip":          <true | false>,
  "hard_skip_reason":   <"reason string if hard_skip is true, else empty string">,
  "recommended_resume": <"A" | "B">,
  "reason":             <"2-3 sentence explanation of the score and fit">
}

Scoring rules:
- total_score = domain_score + ai_readiness_score + skills_score + level_score  (max 10)
- track: "DUAL" if domain_score >= 2 AND ai_readiness_score >= 2; "AI" if ai_readiness_score == 3; "ADTECH" if domain_score == 3 AND ai_readiness_score < 2; else "LOW MATCH"
- tier: total_score >= 9 → "Tier 1"; 7-8 → "Tier 2"; 5-6 → "Tier 3"; < 5 → "Skip"
- hard_skip: true if ANY of these apply:
    * total_score <= 6
    * Salary top of range clearly under $200K (if visible in the description)
    * Job requires production Python or TypeScript as a hard requirement
    * Role is sales, revenue, or account management — not product
    * Company is an agency, not a product company
- recommended_resume: "B" if ai_readiness_score == 3; "A" if domain is adtech-specific; else "B"
- ai_score = same as ai_readiness_score
- adtech_score = domain_score when domain is adtech-specific, else 0
""".strip()


def build_prompt(job: dict) -> str:
    title   = job.get("title", "")
    company = job.get("company", "")
    loc     = job.get("location", "")
    salary  = job.get("salary_text", "") or "not listed"
    desc    = (job.get("description", "") or "")[:5000]

    return f"""Score this job posting for the candidate below.

JOB POSTING:
Title:    {title}
Company:  {company}
Location: {loc}
Salary:   {salary}
Description:
{desc}

---
CANDIDATE PROFILE:
{CANDIDATE_PROFILE}
{RESUME_SECTION}

---
{JSON_SCHEMA}"""


def _call_claude(prompt: str) -> Optional[dict]:
    """
    Makes one Claude API call and parses the JSON response.
    Returns the parsed dict, or raises ValueError/APIError on failure.
    """
    msg = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=GUARDRAILS,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": EFFORT},
        timeout=30,
    )
    raw = msg.content[0].text.strip()

    if not raw:
        raise ValueError("Claude returned an empty response")

    # Strip markdown code fences if Claude included them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)  # raises json.JSONDecodeError if unparseable


def score_job(job: dict) -> Optional[dict]:
    """
    Scores one job with up to 2 Claude attempts.
    Attempt 1 fails → wait 2 s → attempt 2.
    Both fail → log and return None so the run continues.
    """
    job_id = job.get("job_id", "")
    prompt = build_prompt(job)

    for attempt in (1, 2):
        try:
            return _call_claude(prompt)
        except (ValueError, json.JSONDecodeError) as e:
            if attempt == 1:
                print(f"  [retry] Attempt 1 failed for {job_id} ({e}) — retrying in 2 s ...", file=sys.stderr)
                time.sleep(2)
            else:
                print(f"  [error] Attempt 2 also failed for {job_id} ({e}) — skipping.", file=sys.stderr)
        except anthropic.APITimeoutError:
            if attempt == 1:
                print(f"  [retry] API timeout on attempt 1 for {job_id} — retrying in 10 s ...", file=sys.stderr)
                time.sleep(10)
            else:
                print(f"  [error] API timeout on attempt 2 for {job_id} — skipping.", file=sys.stderr)
        except anthropic.APIError as e:
            if hasattr(e, "status_code") and e.status_code == 400 and "credit" in str(e).lower():
                raise RuntimeError("CREDIT_EXHAUSTED")
            if attempt == 1:
                print(f"  [retry] API error on attempt 1 for {job_id} ({e}) — retrying in 2 s ...", file=sys.stderr)
                time.sleep(2)
            else:
                print(f"  [error] API error on attempt 2 for {job_id} ({e}) — skipping.", file=sys.stderr)

    return None


# ── 4. Main ───────────────────────────────────────────────────────────────────

# --estimate  → count unscored rows, estimate token usage and cost, then exit
ESTIMATE_MODE = "--estimate" in sys.argv

# --preview N  → score N rows, print raw JSON, do NOT write to sheet
PREVIEW_MODE  = "--preview" in sys.argv
PREVIEW_LIMIT = 5
if PREVIEW_MODE:
    try:
        PREVIEW_LIMIT = int(sys.argv[sys.argv.index("--preview") + 1])
    except (IndexError, ValueError):
        PREVIEW_LIMIT = 5

# --limit N  → score and write only N rows, then stop
LIMIT_MODE  = "--limit" in sys.argv
LIMIT_COUNT = None
if LIMIT_MODE:
    try:
        LIMIT_COUNT = int(sys.argv[sys.argv.index("--limit") + 1])
    except (IndexError, ValueError):
        LIMIT_COUNT = 10

print("\nOpening sheet ...")
sheet = sheets.open_or_create_sheet()

print("Reading rows ...")
all_rows = sheets.get_all_rows_with_numbers(sheet)

# Filter to rows that need scoring
to_score = [
    r for r in all_rows
    if not str(r.get("ai_score", "")).strip()
    and not str(r.get("adtech_score", "")).strip()
    and r.get("status", "").lower() not in USER_OWNED_STATUSES
]

if PREVIEW_MODE:
    to_score = to_score[:PREVIEW_LIMIT]
    print(f"  PREVIEW MODE — scoring {len(to_score)} row(s), nothing will be written to the sheet.\n")
elif LIMIT_MODE:
    to_score = to_score[:LIMIT_COUNT]
    print(f"  LIMIT MODE — scoring first {len(to_score)} rows only, will write to sheet.\n")
else:
    print(f"  {len(all_rows)} total rows | {len(to_score)} unscored and eligible\n")

if ESTIMATE_MODE:
    # Sonnet 4.6 pricing (per 1M tokens)
    INPUT_PRICE_PER_M  = 3.00
    OUTPUT_PRICE_PER_M = 15.00
    AVG_OUTPUT_TOKENS  = 250  # typical JSON response

    # Sample 10 evenly spaced rows to estimate average prompt size
    sample_size = min(10, len(to_score))
    step = max(1, len(to_score) // sample_size)
    sample = [to_score[i] for i in range(0, len(to_score), step)][:sample_size]

    total_sample_tokens = 0
    for row in sample:
        prompt = build_prompt(row)
        resp = client.messages.count_tokens(
            model=MODEL,
            system=GUARDRAILS,
            messages=[{"role": "user", "content": prompt}],
        )
        total_sample_tokens += resp.input_tokens

    avg_input_tokens = total_sample_tokens // len(sample)
    n = len(to_score)

    total_input  = avg_input_tokens * n
    total_output = AVG_OUTPUT_TOKENS * n
    cost_input   = total_input  / 1_000_000 * INPUT_PRICE_PER_M
    cost_output  = total_output / 1_000_000 * OUTPUT_PRICE_PER_M
    total_cost   = cost_input + cost_output
    est_minutes  = (n * 10) // 60  # ~10s per job

    print(f"""
{'='*50}
COST ESTIMATE — match_scorer.py ({MODEL}, effort={EFFORT})
{'='*50}
Unscored jobs:        {n}
Sample size:          {len(sample)} rows
Avg input tokens:     {avg_input_tokens:,} per call
Avg output tokens:    {AVG_OUTPUT_TOKENS} per call (estimated)

Total input tokens:   {total_input:,}
Total output tokens:  {total_output:,}

Input cost  ($3/M):   ${cost_input:.2f}
Output cost ($15/M):  ${cost_output:.2f}
TOTAL COST:           ${total_cost:.2f}

Est. runtime:         ~{est_minutes} min at ~10s/job
{'='*50}
""")
    sys.exit(0)

if not to_score:
    print("Nothing to score. Exiting.")
    sys.exit(0)

# ── 5. Score each job ─────────────────────────────────────────────────────────

updates   = []
failed    = []
counters  = Counter()
FLUSH_EVERY = 25  # write to sheet every N scored jobs to preserve progress

for i, row in enumerate(to_score, 1):
    job_id  = row.get("job_id", "")
    title   = row.get("title", "")
    company = row.get("company", "")
    print(f"{'='*55}")
    print(f"[{i}/{len(to_score)}] {datetime.now().strftime('%H:%M:%S')}  {title} @ {company}")
    print(f"  job_id: {job_id}")
    print(f"  description chars: {len(row.get('description', '') or '')}")

    try:
        result = score_job(row)
    except RuntimeError as e:
        if str(e) == "CREDIT_EXHAUSTED":
            print(f"\n[FATAL] Anthropic credit balance exhausted.", file=sys.stderr)
            print(f"  Top up at console.anthropic.com → Plans & Billing, then re-run.", file=sys.stderr)
            if updates and not PREVIEW_MODE:
                print(f"  Writing {len(updates)} scores collected so far ...")
                sheets.batch_write_scores(sheet, updates)
                print(f"  Saved. Re-run after topping up — scored rows will be skipped automatically.")
            sys.exit(1)
        raise

    if result is None:
        failed.append(job_id)
        counters["errors"] += 1
        time.sleep(CALL_DELAY_SECONDS)
        continue

    if PREVIEW_MODE:
        # Print raw JSON and stop — do not collect for writing
        print(f"\n  RAW JSON RESPONSE:")
        print(json.dumps(result, indent=4))
        time.sleep(CALL_DELAY_SECONDS)
        continue

    # ── Map Claude output → sheet columns ──
    total  = result.get("total_score", 0)
    track  = result.get("track", "LOW MATCH")
    tier   = result.get("tier", "Skip")
    skip   = result.get("hard_skip", True)
    reason = result.get("reason", "")
    resume = result.get("recommended_resume", "B")

    match_flag        = track
    recommended_track = f"{tier} | {track}"

    if skip or tier == "Skip":
        status = "low match"
    elif tier in ("Tier 1", "Tier 2"):
        status = "ready to apply"
    else:
        status = "spray"

    current_status = str(row.get("status", "")).strip().lower()
    write_status   = current_status in ("", "new")

    updates.append({
        "row_num":           row["_row_num"],
        "ai_score":          result.get("ai_score", 0),
        "adtech_score":      result.get("adtech_score", 0),
        "match_flag":        match_flag,
        "recommended_track": recommended_track,
        "notes":             reason,
        "status":            status,
        "write_status":      write_status,
    })

    counters[tier]  += 1
    counters[track] += 1
    if skip:
        counters["hard_skip"] += 1

    print(f"    score={total}  tier={tier}  track={track}  resume={resume}  hard_skip={skip}")
    time.sleep(CALL_DELAY_SECONDS)

    if not PREVIEW_MODE and len(updates) >= FLUSH_EVERY:
        print(f"\n  [flush] Writing {len(updates)} scores to sheet ...")
        sheets.batch_write_scores(sheet, updates)
        updates.clear()
        print(f"  [flush] Done.\n")

# ── 6. Write all scores in one batch (skipped in preview mode) ───────────────

if PREVIEW_MODE:
    print(f"\n{'='*55}")
    print("PREVIEW COMPLETE — sheet unchanged. Run without --preview to write scores.")
    sys.exit(0)

if updates:
    print(f"\nWriting {len(updates)} score rows to sheet ...")
    sheets.batch_write_scores(sheet, updates)
    print("  Done.")

if failed:
    print(f"\n  [warning] {len(failed)} job(s) failed and were skipped:")
    for jid in failed:
        print(f"    {jid}")

# ── 7. Summary ────────────────────────────────────────────────────────────────

scored = len(updates)
print(f"""
{'='*45}
SCORING COMPLETE
{'='*45}
Total scored:      {scored}
Tier 1:            {counters.get('Tier 1', 0)}
Tier 2:            {counters.get('Tier 2', 0)}
Tier 3:            {counters.get('Tier 3', 0)}
Skip / low match:  {counters.get('Skip', 0)}
Hard skips:        {counters.get('hard_skip', 0)}
---
AI track:          {counters.get('AI', 0)}
ADTECH track:      {counters.get('ADTECH', 0)}
DUAL:              {counters.get('DUAL', 0)}
LOW MATCH:         {counters.get('LOW MATCH', 0)}
Errors:            {counters.get('errors', 0)}
{'='*45}
""")
