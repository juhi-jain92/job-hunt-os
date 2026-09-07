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
    python3 -m stages.match_scorer --rescore-below 7   re-score rows under 7
    python3 -m stages.match_scorer --rescore-all      re-price the whole ledger
                                          (user-owned statuses untouched)
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

from lib import sheets

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv()
API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY or API_KEY == "your_key_here":
    sys.exit("ERROR: Set ANTHROPIC_API_KEY in your .env file.")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = json.load(open(os.path.join(BASE, "config", "search_config.json")))["scorer_settings"]

MODEL  = _cfg.get("model", "claude-sonnet-5")
EFFORT = _cfg.get("effort", "low")
PRICE_IN  = _cfg.get("price_input_per_m", 2.00)
PRICE_OUT = _cfg.get("price_output_per_m", 10.00)

USER_OWNED_STATUSES = sheets.JOB_USER_STATUSES
FLUSH_EVERY = 25
CALL_DELAY  = 0.1

client = anthropic.Anthropic(api_key=API_KEY)

# ── Candidate context ─────────────────────────────────────────────────────────
# Preferences come from the gitignored context store; the resume key details
# are distilled from resume/Juhi_Jain_Resume.pdf (Aug 2026). Refresh the
# KEY_DETAILS block when the PDF changes.

try:
    _store = json.load(open(os.path.join(BASE, "config", "context_store.json")))
except FileNotFoundError:
    # Gitignored personal file; absent in CI. Resume-level facts suffice, but
    # say so: these defaults are narrower than the real store (no Bay Area).
    print("  [warning] config/context_store.json absent — scoring with default "
          "preferences (Seattle/Remote only, remote-first). Cloud and local "
          "scores can differ on location.", file=sys.stderr)
    _store = {"candidate": {"name": "Juhi Jain", "yoe": 10, "location": "Seattle, WA"},
              "shared": {"locations": ["Seattle", "Remote"], "remote_preference": "remote-first",
                         "salary": {"tc_floor": 200000},
                         "seniority_band": ["Senior PM", "Principal PM", "Director"]}}
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
You are a job-fit scorer optimizing for REFERRAL-WORTHINESS, not offer-worthiness.
The question is not "is she the ideal candidate." It is: if a warm contact referred
her for this role, would a recruiter reasonably take a 30-minute screen? Default to
yes for any product-management role at Senior level or above in a software company.
Be generous on domain and specific about dealbreakers. Never inflate seniority or
invent skills; leniency lives in transferability, not in facts.

Return ONLY a valid JSON object, no markdown fences, no prose:

{
  "domain":  <0-3 TRANSFERABILITY of her domain experience to this job's domain.
              3 = adtech, CTV, media, streaming, retail media, marketing tech.
              2 = any two-sided or real-time system: marketplaces, payments, fintech
                  ops, commerce, identity/data platforms, developer platforms, API
                  products, B2B SaaS with ops or workflow automation, analytics.
              1 = any other software product domain (consumer, health software,
                  edtech, HR tech, logistics, gaming, and similar).
              0 = ONLY if the domain requires credentials or background she cannot
                  claim: clinical/medical practice, licensed finance, hardware or
                  semiconductor engineering, defense clearance.>,

  "ai":      <0-3 AI RELEVANCE and her fit for it.
              3 = AI is the product or the core of the role: LLM features, agents,
                  evals, AI platform, model APIs, AI-native workflows.
              2 = AI is a meaningful part of the role or roadmap: AI features inside
                  a larger product, AI adoption, automation, personalization, ML-
                  powered decisioning.
              1 = no AI in the role, but a real product role at an AI-curious or
                  data-heavy company. She brings AI depth as a differentiator.
              0 = ONLY if the role is ML engineering, research science, or requires
                  hands-on model training, fine-tuning, or RAG implementation.>,

  "skills":  <0-2 OVERLAP between the JD's top responsibilities and her tracks.
              2 = the first three responsibilities map to at least two of: 0-to-1
                  product building, platform or marketplace ownership, AI product
                  work with evals/guardrails/HITL, monetization or growth, data or
                  identity infrastructure, ops enablement, cross-functional and
                  executive stakeholder leadership.
              1 = at least one maps clearly.
              0 = none map (rare for a PM role; use sparingly).>,

  "level":   <0-2 SENIORITY FIT. Be strict here; this one is a gate, not a
              preference, and a wrong 2 puts a junior role in front of her.
              2 = the title carries a seniority marker: Senior, Sr., Staff,
                  Principal, Lead, Group PM, Director of Product, Head of
                  Product, Associate Director, VP Product at a startup, or a
                  founding/first-PM role.
              1 = no seniority marker: plain "Product Manager", "Product Owner",
                  "Technical Product Manager", or a title whose scope is
                  genuinely unclear.
              0 = explicitly junior (APM, Associate PM, entry level, intern) or
                  far above the band (VP/CPO/SVP at a large company).>,

  "dealbreaker": <"" or ONE of these exact reasons, nothing else counts:
              "comp under floor" (posted top of range clearly under $200K total),
              "coding required" (production code as a stated hard requirement),
              "not product" (sales, account management, customer success, program/
              project management, marketing, consulting delivery, solutions eng),
              "agency or contract" (staffing agency, contract-to-hire, W2 contract,
              recruiting firm posting on behalf of unnamed client),
              "location" (ONSITE-ONLY, no remote and no hybrid, in a city that is
              NOT in the Seattle metro (Seattle, Bellevue, Redmond, Kirkland) and
              NOT in the SF Bay Area (San Francisco, Palo Alto, Menlo Park, Mountain
              View, Sunnyvale, San Jose, Redwood City, Oakland, South SF). Bay Area
              onsite is ACCEPTABLE, never a dealbreaker. Hybrid anywhere is a
              reason, not a dealbreaker.),
              "credential" (requires a license, clearance, or PhD).
              Everything else is a reason, not a dealbreaker: adjacent domain, one
              missing nice-to-have, unfamiliar industry, unstated comp, hybrid.>,

  "reason":  <2 sentences. First: the strongest reason a referral makes sense (name
              the track or story that maps). Second: the one gap she should know
              before a screen, or "no material gap".>
}

CALIBRATION. A healthy scan of real Senior+ PM postings should land 35 to 50 percent
at 7 or above. If you find yourself below 6 on most software PM roles, you are
scoring for offer, not referral. Anchors:
- Sr PM, content conversion, streaming company, no AI in JD: 3+1+2+2 = 8.
- Principal PM, AI-native operations platform, B2B payments: 2+3+2+2 = 9.
- Senior PM, model APIs and developer experience, AI inference: 2+3+2+2 = 9.
- Staff PM, developer tooling company, AI features on roadmap: 2+2+2+2 = 8.
- PM (no level), consumer health app, no AI: 1+1+1+1 = 4 (reason, not dealbreaker).
- Senior PM, marketplace ops, $150-180K posted: dealbreaker "comp under floor".
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
    # strict=False tolerates literal newlines and tabs inside JSON strings,
    # which the model emits in long 'reason' values. Without it each one costs
    # two retries and two extra billed calls.
    return json.loads(raw.strip(), strict=False)


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
    # Seniority is a gate, not a dimension to be outvoted: a lenient domain and
    # AI score can carry a plain "Product Manager" posting past 7, and she does
    # not apply to those. Enforce it in Python so it cannot depend on the model
    # remembering to say so.
    if not dealbreaker and level <= 1:
        dealbreaker = ("below her band" if level == 0
                       else "no seniority marker in the title")
    skip = bool(dealbreaker) or score <= 6

    status = "low match" if skip else "ready to apply"
    reason = result.get("reason", "")
    if dealbreaker:
        reason = f"DEALBREAKER: {dealbreaker}. {reason}"

    return {
        "score":        score,
        "notes":        reason,
        "status":       status,
        # Script-owned statuses may be rewritten (a --rescore-below pass must
        # be able to lift "low match" to "ready to apply"); user-owned never.
        "write_status": current_status in ("", "new", "low match", "ready to apply"),
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
RESCORE_BELOW = 11 if "--rescore-all" in sys.argv else _flag("--rescore-below", 7)


def main():
    print("\nOpening sheet ...")
    sheet = sheets.open_or_create_sheet()
    all_rows = sheets.get_all_rows_with_numbers(sheet)

    def _num(v):
        try:
            return float(str(v).strip())
        except ValueError:
            return None

    if RESCORE_BELOW is not None:
        # Rubric changed: re-price every row that scored under the gate. Rows
        # at or above the gate and user-owned rows are never touched.
        to_score = [
            r for r in all_rows
            if _num(r.get("score", "")) is not None
            and _num(r.get("score", "")) < RESCORE_BELOW
            and (r.get("status", "") or "").lower() not in USER_OWNED_STATUSES
        ]
        print(f"  RESCORE — rows currently under {RESCORE_BELOW}: {len(to_score)}")
    else:
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
            # score <= 6 or a dealbreaker — scored and recorded, just not
            # worth applying to. Named "low match", because a run summary
            # saying "skipped 847" reads as work not done.
            counters["low match"] += 1
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
