"""
match_scorer.py — Scores every unscored job in the ledger against Juhi's
resume key details, writing one score (0-10), status, and notes back to
the sheet.

Division of labor: the model judges four dimensions and the qualitative
dealbreakers; Python does every derivation (total, sub-score mapping,
status). An A/B showed the model mislabels its own arithmetic ~1/3 of the
time at low effort, so no derived value is ever asked of it.

Model: claude-sonnet-5 at effort low — A/B-tested as the optimum. Medium
effort doubled cost and changed zero 7+ decisions; disabling thinking was
slower AND more expensive (the model pads visible output instead).

Usage:
    python3 match_scorer.py --estimate     cost estimate, no scoring
    python3 match_scorer.py --preview 5    score 5, print JSON, write nothing
    python3 match_scorer.py --limit 20     score and write only 20
    caffeinate -dims python3 match_scorer.py
"""

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime

import anthropic
from dotenv import load_dotenv

import sheets

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY or API_KEY == "your_key_here":
    sys.exit("ERROR: Set ANTHROPIC_API_KEY in your .env file.")

BASE = os.path.dirname(__file__)
_cfg = json.load(open(os.path.join(BASE, "config", "search_config.json")))["scorer_settings"]

MODEL  = _cfg.get("model", "claude-sonnet-5")
EFFORT = _cfg.get("effort", "low")
PRICE_IN  = _cfg.get("price_input_per_m", 2.00)
PRICE_OUT = _cfg.get("price_output_per_m", 10.00)

USER_OWNED_STATUSES = {"applied", "interviewing", "rejected", "skipped"}
FLUSH_EVERY = 25
CALL_DELAY  = 0.1

client = anthropic.Anthropic(api_key=API_KEY)

# ── Candidate context ─────────────────────────────────────────────────────────
# Preferences come from the gitignored context store; the resume key details
# are distilled from resume/Juhi_Jain_Resume.pdf (Aug 2026). Refresh the
# KEY_DETAILS block when the PDF changes.

_store  = json.load(open(os.path.join(BASE, "config", "context_store.json")))
_cand   = _store.get("candidate", {})
_shared = _store.get("shared", {})

PREFERENCES = f"""
CANDIDATE: {_cand.get('name', '')} — {_cand.get('yoe', '')} yrs PM
Location: {_cand.get('location', '')} · OK: {', '.join(_shared.get('locations', []))} · {_shared.get('remote_preference', '')}
Salary floor: ${_shared.get('salary', {}).get('tc_floor', 200000):,} total comp
Seniority band: {', '.join(_shared.get('seniority_band', []))}
""".strip()

KEY_DETAILS = """
--- CURRENT POSITIONING ---
AI-native Product Leader, ~10 yrs, 0-to-1 products across programmatic advertising,
CTV and applied AI, grounded in hands-on predictive modeling. Owned strategy and
roadmap for a $400M business; shipped three AI-enabled workflows using deterministic
decisioning, evals, guardrails and human review — $2M annualized, $10M+ projected.

--- AI / BUILDER TRACK ---
- Now: AI Product Manager, Vectorial AI (Jul 2026–present) — founding product member
  on a production voice-AI interview agent; North Star metric, quality rubrics, data
  strategy; v1 roadmap adopted by the CPO in week one
- Evals & observability: golden-dataset evals, LLM-as-judge, regression gates,
  turn-level OpenTelemetry tracing; cut cost 75% ($4 → $1 per interview)
- Trust & safety: deterministic controls (PII stripping, kill switch, jailbreak and
  fraud guardrails) gating every live session, vs LLM-judged quality calls
- Re-architected a multi-agent voice system into a deterministic stateful gateway
  owning transcript, live-time injection, and memory with context compaction
- Prior: Associate Director, PM at LG Ads (Apr 2025–Apr 2026); managed 4 PMs
- AI portfolio at LG Ads: creative approval (policy rules, confidence guardrails,
  3-state risk routing; TAT 5 days → 1 day, ~80% automated, HITL on riskiest 20%),
  multimodal creative generation, campaign-diagnostics agent (LLM for intent routing
  and explanation only; 4 hrs → real-time, 50% ticket deflection, $1.5M/yr)
- Independent builds: Job Hunt OS (LLM scoring 2,000+ roles, human-review gate),
  ThinkOS (propose-never-modify git gate), ContractIQ (full-stack legal-AI on Azure
  AI/Snowflake/Supabase), Interview Coach (self-updating eval rubric)
- Fluency: SQL, REST APIs, Azure AI, Snowflake, Supabase, OpenTelemetry, Git

--- ADTECH TRACK ---
- Owned $400M programmatic business: demand, supply, identity, monetization across
  CTV video and display; product voice to 10+ clients, SSPs, DSPs, CXO partners
- Identity (contrarian bet): UID2, RampID, Google PAL, APS across US/CA/EU;
  tripled bid rates, 60% O&O CTV coverage, $3M rev/year
- Monetization: 0-to-1 home-screen inventory, first TV OEM to enable it across all
  ad formats; 10+ DSPs/SSPs/resellers; $16M annual revenue in 1.5 years
- Inventory quality: fraud detection in-house, threshold set where false-block cost
  met fraud loss; $4M, +20% margin. Supply diagnostics across 2,500+ tags; $1.3M
- Production ML: per-partner bid-propensity model, weekly retraining; $1.2M
- Privacy: GDPR/CCPA/DNT-LMT; caught a $6M GDPR gap, drove EU to 60%+ opt-in
- CTV/OTT: River OS to 100K TVs in under a year; voice household-ID integrated by
  LGE across 100M+ TVs; CES 2022 demo; Most Revenue Generating PM 2023

--- HONEST LIMITS (never claim) ---
- Production Python/TypeScript coding, LLM fine-tuning, hands-on RAG pipelines,
  vector database implementation
- Seniority above Associate Director
- Independent builds are portfolio projects, not shipped commercial products
""".strip()

RUBRIC = """
You are a precise, honest job-fit scorer. Never inflate scores. If the JD requires
something the candidate lacks, or the description is too thin to judge, say so in
"reason".

Return ONLY a valid JSON object, no markdown fences, no prose:

{
  "domain":          <0-3  how well the job's domain matches adtech/CTV/programmatic experience>,
  "ai":              <0-3  how central applied-AI product work is to this job and how well she fits it>,
  "skills":          <0-2  overlap between JD requirements and her actual skills>,
  "level":           <0-2  seniority and scope fit for a Senior PM-to-Director band>,
  "dealbreaker":     <"" or the reason: salary top clearly under the floor, production
                      coding as a hard requirement, sales/account role not product,
                      agency not product company>,
  "reason":          <2-3 sentences: why these scores, and any gap worth knowing>
}

Judge leniently on domain when the AI fit is genuine: a strong AI-core role in an
adjacent domain (healthtech, fintech) is not a low match — let the ai dimension carry it.
""".strip()

# Everything static sits in the system prompt with cache_control, in stable
# order; only the job posting varies per call. ~4K of ~5K input tokens are
# billed at the 0.1x cache-read rate from the second call on.
SYSTEM_BLOCKS = [{
    "type": "text",
    "text": f"{RUBRIC}\n\n---\n{PREFERENCES}\n\n{KEY_DETAILS}",
    "cache_control": {"type": "ephemeral"},
}]


def build_prompt(job: dict) -> str:
    return (
        f"Score this job posting for the candidate in your instructions.\n\n"
        f"JOB POSTING:\n"
        f"Title:    {job.get('title', '')}\n"
        f"Company:  {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Description:\n{(job.get('description') or '')[:5000]}"
    )


# ── Scoring ───────────────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> dict:
    # max_tokens covers thinking + JSON; a low ceiling truncates mid-object.
    msg = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_BLOCKS,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": EFFORT},
        timeout=60,
    )
    # The response may open with a thinking block — take the first text block.
    raw = next(
        (b.text.strip() for b in msg.content
         if getattr(b, "type", None) == "text" and b.text.strip()),
        "",
    )
    if not raw:
        kinds = ", ".join(getattr(b, "type", "?") for b in msg.content)
        raise ValueError(f"no text block in response ({kinds})")
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
    return json.loads(raw.strip())


def score_job(job: dict):
    """Two attempts, then skip. CREDIT_EXHAUSTED aborts the run upstream."""
    prompt = build_prompt(job)
    for attempt in (1, 2):
        try:
            return _call_claude(prompt)
        except anthropic.APIError as e:
            if getattr(e, "status_code", None) == 400 and "credit" in str(e).lower():
                raise RuntimeError("CREDIT_EXHAUSTED")
            err, wait = e, 10 if isinstance(e, anthropic.APITimeoutError) else 2
        except (ValueError, json.JSONDecodeError) as e:
            err, wait = e, 2
        if attempt == 1:
            print(f"  [retry] {err} — retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    print(f"  [error] both attempts failed for {job.get('job_id', '')} — skipping", file=sys.stderr)
    return None


def derive(result: dict, current_status: str) -> dict:
    """
    Everything computable from the model's judgment, computed here.
    score = sum of dimensions; the referral lane gates on score >= 7.
    """
    domain = int(result.get("domain", 0))
    ai     = int(result.get("ai", 0))
    skills = int(result.get("skills", 0))
    level  = int(result.get("level", 0))
    score  = domain + ai + skills + level

    dealbreaker = str(result.get("dealbreaker", "") or "").strip()
    skip = bool(dealbreaker) or score <= 6

    status = "low match" if skip else "ready to apply" if score >= 7 else "spray"
    reason = result.get("reason", "")
    if dealbreaker:
        reason = f"DEALBREAKER: {dealbreaker}. {reason}"

    return {
        "score":        score,
        "notes":        reason,
        "status":       status,
        "write_status": current_status in ("", "new"),
        "skip":         skip,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def _flag(name, default):
    """N after the flag, the default if N is missing, None if the flag is absent."""
    if name not in sys.argv:
        return None
    try:
        return int(sys.argv[sys.argv.index(name) + 1])
    except (IndexError, ValueError):
        return default


ESTIMATE = "--estimate" in sys.argv
PREVIEW  = _flag("--preview", 5)
LIMIT    = _flag("--limit", 10)


def main():
    print("\nOpening sheet ...")
    sheet = sheets.open_or_create_sheet()
    all_rows = sheets.get_all_rows_with_numbers(sheet)

    to_score = [
        r for r in all_rows
        if not str(r.get("score", "")).strip()
        and (r.get("status", "") or "").lower() not in USER_OWNED_STATUSES
    ]

    # Rows with nothing to read are marked, not sent — a model call cannot
    # score a job it cannot see.
    def scorable(r):
        return (str(r.get("job_id", "")).strip()
                and str(r.get("title", "")).strip()
                and len(str(r.get("description", "")).strip()) >= 100)

    unscorable = [r for r in to_score if not scorable(r)]
    to_score   = [r for r in to_score if scorable(r)]

    if unscorable and not (ESTIMATE or PREVIEW):
        sheets.batch_write_scores(sheet, [{
            "row_num": r["_row_num"], "score": 0,
            "notes": ("No description from the source — cannot be scored."
                      if str(r.get("title", "")).strip()
                      else "Empty row."),
            "status": "low match", "write_status": True,
        } for r in unscorable])
        print(f"  Marked {len(unscorable)} unscorable row(s) without model calls.")
    elif unscorable:
        print(f"  Ignoring {len(unscorable)} unscorable row(s).")

    print(f"  {len(all_rows)} rows | {len(to_score)} unscored and eligible\n")

    if ESTIMATE:
        estimate(to_score)
        return
    if PREVIEW:
        to_score = to_score[:PREVIEW]
        print(f"  PREVIEW — scoring {len(to_score)}, writing nothing.\n")
    elif LIMIT:
        to_score = to_score[:LIMIT]

    updates, counters, t0 = [], Counter(), time.time()

    for i, row in enumerate(to_score, 1):
        print(f"[{i}/{len(to_score)}] {datetime.now():%H:%M:%S}  "
              f"{row.get('title', '')[:60]} @ {row.get('company', '')}")
        try:
            result = score_job(row)
        except RuntimeError:
            print("\n[FATAL] Anthropic credits exhausted — saving progress.", file=sys.stderr)
            if updates and not PREVIEW:
                sheets.batch_write_scores(sheet, updates)
            sys.exit(1)

        if result is None:
            counters["errors"] += 1
            continue

        if PREVIEW:
            print(json.dumps(result, indent=2))
            d = derive(result, str(row.get("status", "")).strip().lower())
            print(f"  → would write: score={d['score']}  status={d['status']}")
            continue

        d = derive(result, str(row.get("status", "")).strip().lower())
        updates.append({"row_num": row["_row_num"], **{
            k: d[k] for k in ("score", "notes", "status", "write_status")
        }})
        counters[f"score {d['score']}"] += 1
        if d["skip"]:
            counters["skipped"] += 1
        print(f"    score={d['score']}  status={d['status']}")

        if len(updates) >= FLUSH_EVERY:
            sheets.batch_write_scores(sheet, updates)
            updates.clear()
            print(f"  [flush] saved · {i}/{len(to_score)} done · "
                  f"{(time.time() - t0) / i:.1f}s/job avg")
        time.sleep(CALL_DELAY)

    if updates:
        sheets.batch_write_scores(sheet, updates)

    print(f"\nDone in {(time.time() - t0) / 60:.0f} min.")
    for label, n in counters.most_common():
        print(f"  {label:<12} {n}")


def estimate(to_score: list):
    if not to_score:
        print("  Nothing to score.")
        return
    sample = to_score[:: max(1, len(to_score) // 10)][:10]
    prefix = client.messages.count_tokens(
        model=MODEL, system=SYSTEM_BLOCKS,
        messages=[{"role": "user", "content": "x"}],
    ).input_tokens
    var = sum(
        client.messages.count_tokens(
            model=MODEL, messages=[{"role": "user", "content": build_prompt(r)}]
        ).input_tokens
        for r in sample
    ) // len(sample)

    n = len(to_score)
    # Cached prefix: 1.25x once, 0.1x on every later call.
    cost = (
        (var * n + prefix * 1.25 + prefix * (n - 1) * 0.10) / 1e6 * PRICE_IN
        + 250 * n / 1e6 * PRICE_OUT
    )
    print(f"  {n} jobs · ~{prefix} cached + ~{var} variable tokens/call")
    print(f"  Estimated cost: ${cost:.2f} · runtime ~{n * 6 // 60} min")


if __name__ == "__main__":
    main()
