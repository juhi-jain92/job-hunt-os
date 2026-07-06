"""
match_scorer.py — Reads every unscored job from the "Job Hunt OS" sheet,
calls an LLM once per job to score it against the configured search tracks,
then batch-writes all scores back to the sheet.

Supported providers (set in config/search_config.json → scorer_settings.provider):
  "anthropic" — Claude models via ANTHROPIC_API_KEY
  "zhipuai"   — GLM models via ZAI_API_KEY
"""

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Optional

import anthropic
from openai import OpenAI
from zhipuai import ZhipuAI
from dotenv import load_dotenv

import sheets

# ── 1. Config & secrets ──────────────────────────────────────────────────────

load_dotenv()

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

context_store    = json.loads(open(os.path.join(BASE, "config", "context_store.json")).read())
_search_config   = json.loads(open(os.path.join(BASE, "config", "search_config.json")).read())
_scorer_settings = _search_config.get("scorer_settings", {})
PROVIDER         = _scorer_settings.get("provider", "anthropic")
_defaults = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-4o-mini", "zhipuai": "glm-4-flash"}
_default_model   = _defaults.get(PROVIDER, "claude-sonnet-4-6")
MODEL            = _scorer_settings.get("model", _default_model)

if PROVIDER == "anthropic":
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY in {"your_key_here", "your_anthropic_api_key_here"}:
        sys.exit("ERROR: Set ANTHROPIC_API_KEY in your .env file. Get it at console.anthropic.com → API Keys.")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
elif PROVIDER == "openai":
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_API_KEY or OPENAI_API_KEY in {"your_key_here", "your_openai_api_key_here"}:
        sys.exit("ERROR: Set OPENAI_API_KEY in your .env file. Get it at platform.openai.com/api-keys.")
    client = OpenAI(api_key=OPENAI_API_KEY)
elif PROVIDER == "zhipuai":
    ZAI_API_KEY = os.getenv("ZAI_API_KEY")
    if not ZAI_API_KEY or ZAI_API_KEY in {"your_key_here", "your_zai_api_key_here"}:
        sys.exit("ERROR: Set ZAI_API_KEY in your .env file. Get it at bigmodel.cn → API Keys.")
    client = ZhipuAI(api_key=ZAI_API_KEY)
else:
    sys.exit(f"ERROR: Unknown provider '{PROVIDER}' in search_config.json. Use 'anthropic', 'openai', or 'zhipuai'.")
rubric_text      = _load("config/job_fit_eval_framework.md", "eval framework")

# Guardrails: load from file if it exists, otherwise use inline version
_guardrails_file = _load("guardrails/guardrails.md", "guardrails file")
GUARDRAILS = _guardrails_file if _guardrails_file else """
You are a precise, honest job-fit scorer. Apply these rules without exception:

ACCURACY
- Never add skills, titles, or experience not explicitly in the candidate's resume
- Never exaggerate metrics — exact numbers only, traceable to the experience library
- Score honestly; do not inflate scores to flatter

SCORING BEHAVIOR
- If the JD requires something the candidate clearly lacks, flag it explicitly in the reason field
- If match score confidence is low due to missing or thin JD content, say so explicitly in the reason field
- Score leniently on domain when AI readiness is high: a strong AI-core role in an adjacent domain is NOT an automatic skip — let ai_readiness_score carry the total if the AI fit is genuine
""".strip()

# Build a compact candidate profile string from context_store
_cand    = context_store["candidate"]
_shared  = context_store["shared"]
_tracks  = context_store["tracks"]
_company = context_store["company_profile"]

TRACK_KEYS = list(_tracks.keys())
PRIMARY_TRACK_KEY = "ai" if "ai" in _tracks else TRACK_KEYS[0]
DOMAIN_TRACK_KEY = next((key for key in TRACK_KEYS if key != PRIMARY_TRACK_KEY), PRIMARY_TRACK_KEY)
TRACK_LABELS = {key: _tracks[key].get("track_label", key.upper()) for key in TRACK_KEYS}
TRACK_OPTIONS = list(dict.fromkeys([*TRACK_LABELS.values(), "DUAL", "LOW MATCH"]))


def _format_track(key: str, track: dict) -> str:
    return f"""
{TRACK_LABELS[key]} TRACK positioning: {track['positioning']}
{TRACK_LABELS[key]} TRACK target roles: {', '.join(track['target_roles'])}
{TRACK_LABELS[key]} TRACK must-have signals: {', '.join(track['must_have_signals'])}
{TRACK_LABELS[key]} TRACK boost signals: {', '.join(track.get('boost_signals', []))}
{TRACK_LABELS[key]} TRACK dealbreakers: {'; '.join(track['dealbreakers'])}
""".strip()


TRACK_PROFILE = "\n\n".join(_format_track(key, track) for key, track in _tracks.items())

RESUME_SECTION = "\n\n".join(
    f"--- {TRACK_LABELS[key]} TRACK RESUME ---\n{_load(track.get('resume_path', ''), f'{TRACK_LABELS[key]} resume')}"
    for key, track in _tracks.items()
)

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

{TRACK_PROFILE}
""".strip()

# ── 3. LLM scoring ───────────────────────────────────────────────────────────

JSON_SCHEMA = f"""
Return ONLY a valid JSON object with exactly these keys. No markdown fences, no prose:

{{
  "ai_score":           <int 0-3, AI Readiness dimension score>,
  "domain_score":       <int 0-3, {TRACK_LABELS[DOMAIN_TRACK_KEY]} / domain fit score>,
  "ai_readiness_score": <int 0-3, AI Readiness rubric dimension>,
  "skills_score":       <int 0-2, Skills Match rubric dimension>,
  "level_score":        <int 0-2, Level & Scope rubric dimension>,
  "total_score":        <int, domain_score + ai_readiness_score + skills_score + level_score>,
  "track":              <one of: {', '.join(TRACK_OPTIONS)}>,
  "tier":               <"Tier 1" | "Tier 2" | "Tier 3" | "Skip">,
  "hard_skip":          <true | false>,
  "hard_skip_reason":   <"reason string if hard_skip is true, else empty string">,
  "recommended_resume": <one of: {', '.join(TRACK_LABELS.values())}>,
  "reason":             <"2-3 sentence explanation of the score and fit">
}}

Scoring rules:
- total_score = domain_score + ai_readiness_score + skills_score + level_score  (max 10)
- track: "DUAL" if the role is strong for both the AI and {TRACK_LABELS[DOMAIN_TRACK_KEY]} tracks; "{TRACK_LABELS[PRIMARY_TRACK_KEY]}" if AI readiness is the strongest signal; "{TRACK_LABELS[DOMAIN_TRACK_KEY]}" if domain fit is strongest; else "LOW MATCH"
- tier: total_score >= 9 → "Tier 1"; 7-8 → "Tier 2"; 5-6 → "Tier 3"; < 5 → "Skip"
- hard_skip: true if ANY of these apply:
    * total_score <= 5
    * Salary top of range clearly under the candidate's TC floor (if visible in the description)
    * Role is sales, revenue, account management, support, or solutions-heavy instead of engineering
    * Company is an agency, not a product company
- recommended_resume: choose the configured track label whose resume best fits the posting
- ai_score = same as ai_readiness_score
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


def _raw_anthropic(prompt: str) -> str:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=GUARDRAILS,
        messages=[{"role": "user", "content": prompt}],
        timeout=30,
    )
    return msg.content[0].text.strip()


def _raw_openai(prompt: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": GUARDRAILS},
            {"role": "user", "content": prompt},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def _raw_zhipuai(prompt: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.01,
        thinking={"type": "disabled"},
        max_tokens=1024,
        messages=[
            {"role": "system", "content": GUARDRAILS},
            {"role": "user", "content": prompt},
        ],
    )
    print(f"  [debug] finish_reason={resp.choices[0].finish_reason}", file=sys.stderr)
    content = resp.choices[0].message.content
    print(f"  [debug] raw content={repr(content[:200]) if content else None}", file=sys.stderr)
    return (content or "").strip()


def _call_llm(prompt: str) -> Optional[dict]:
    """
    Makes one LLM API call (provider-agnostic) and parses the JSON response.
    Returns the parsed dict, or raises ValueError/JSONDecodeError on failure.
    """
    _callers = {"anthropic": _raw_anthropic, "openai": _raw_openai, "zhipuai": _raw_zhipuai}
    raw = _callers[PROVIDER](prompt)

    if not raw:
        raise ValueError(f"{PROVIDER} returned an empty response")

    # Strip markdown code fences if the model included them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)  # raises json.JSONDecodeError if unparseable


def score_job(job: dict) -> Optional[dict]:
    """
    Scores one job with up to 2 LLM attempts.
    Attempt 1 fails → wait → attempt 2.
    Both fail → log and return None so the run continues.
    """
    job_id = job.get("job_id", "")
    prompt = build_prompt(job)

    for attempt in (1, 2):
        try:
            return _call_llm(prompt)
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
        except Exception as e:
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
    and not str(r.get("domain_score", "")).strip()
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
    if PROVIDER != "anthropic":
        print(f"--estimate is not supported with provider '{PROVIDER}' (no token-counting API).")
        print(f"  Unscored jobs: {len(to_score)}")
        sys.exit(0)

    INPUT_PRICE_PER_M  = 3.00
    OUTPUT_PRICE_PER_M = 15.00
    AVG_OUTPUT_TOKENS  = 250

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
    est_minutes  = (n * 10) // 60

    print(f"""
{'='*50}
COST ESTIMATE — match_scorer.py
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
scored_count = 0
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

    # ── Map LLM output → sheet columns ──
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
        "domain_score":      result.get("domain_score", result.get("adtech_score", 0)),
        "match_flag":        match_flag,
        "recommended_track": recommended_track,
        "notes":             reason,
        "status":            status,
        "write_status":      write_status,
    })
    scored_count += 1

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

print(f"""
{'='*45}
SCORING COMPLETE
{'='*45}
Total scored:      {scored_count}
Tier 1:            {counters.get('Tier 1', 0)}
Tier 2:            {counters.get('Tier 2', 0)}
Tier 3:            {counters.get('Tier 3', 0)}
Skip / low match:  {counters.get('Skip', 0)}
Hard skips:        {counters.get('hard_skip', 0)}
Errors:            {counters.get('errors', 0)}
{'='*45}
""")

print("Track counts:")
for label in TRACK_OPTIONS:
    print(f"  {label}: {counters.get(label, 0)}")
