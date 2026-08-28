# Job Hunt OS — Architecture

Three stages, one spreadsheet ("Job Hunt OS"), five tabs. Discovery fills the
ledger, the scorer prices every row, the referral and networking lanes turn matches
into drafted asks. **Nothing ever sends — every message leaves from Juhi's hands.**

Status as of 2026-08-28: **fully operational.** 976 jobs discovered · 967 scored
($5.50, 50 min) · 140 at 7+ · 131 rows in the Referrals tab, 67 with a warm path ·
5,855 contacts ingested · Hunter live and verifying.

```
discovery ─▶ ledger ─▶ scorer ─▶ score ≥ 7 ─▶ referral match ─▶ Referrals tab ─┐
                                                    ▲                          ├─▶ notes drafted ─▶ Juhi sends
              contacts (2 CSVs) ────────────────────┘                          │
              target research ─▶ networking daily ─▶ Networking tab ───────────┘
```

## The tabs

| Tab | One row per | Filled by | Juhi's columns |
|---|---|---|---|
| **sheet1** (ledger) | job | discovery + scorer | `status` (applied/rejected/…) |
| **Contacts** | person in either network | contacts_ingest | `tie_type` corrections |
| **Referrals** | role scoring 7+ | referral_match + note drafting | `note_to_send` (copy from), `sent_1/sent_2/sent_rec`, edits |
| **Networking** | cold prospect | networking_daily + note drafting | `draft_body` (copy from), `personalized`, `status`→SENT, `sent_date` |
| **Targets** | company | networking_daily bookkeeping | rarely touched |

---

## Step by step — a job's life, from posting to draft in hand

**Step 1 · Discovery — 5:00am, automatic** (GitHub Actions; manual: `python3 job_search.py`)
Fetches JSearch (18 queries), Greenhouse (38 boards, 8 concurrent), Wellfound, VC
portfolios → normalizes to one schema → dedupes by `job_id` → title filter →
appends to **sheet1** with `status = new`, score blank. Blocked companies dropped
here. ~6–10 min, free.

**Step 2 · Scoring — Juhi's trigger** (`caffeinate -dims python3 match_scorer.py`)
Each unscored row: Sonnet 5 (effort low, prompt-cached) judges 4 dimensions +
dealbreakers against the resume key details; Python sums them into **`score` 0–10**
and writes score/status/notes to **sheet1**. Rows with no description are marked,
not billed. ~3s and ~0.6¢ per job; resumable; `--estimate` first if unsure.
*Not scheduled on purpose — it spends money, so it stays a deliberate action.*

**Step 3 · Contacts — once, then refresh occasionally** (`python3 contacts_ingest.py`)
Parses both LinkedIn exports from `data/connections/` → **Contacts** tab: company
normalized, seniority from title, dormant ties inferred from tenure windows (ISB
and DTU count). Re-running with a fresh export updates people in place.

**Step 4 · Referral match — 9:00am, automatic** (manual: `python3 referral_match.py`)
Every sheet1 row with `score ≥ 7` × Contacts → **Referrals** tab, one row per
role: `first_degree_available`, two ranked referrer slots + a recruiter slot
(clickable names), a title-filtered search link when nobody's inside. Fuzzy company
matches never auto-fill. Re-runs only add new roles — sent rows untouched.

**Step 5 · Networking queue — 9:00am, automatic** (manual: `python3 networking_daily.py`)
Picks 5 company/team slots: manual targets first (Scope3, tvScientific, Kevel,
Chalice — no job posting required), then board-signal picks; big companies split
into product orgs; 14-day cooldown. Per company: **small → 1–2 product leaders only
(VP/Dir/Sr Dir/Principal/Staff/GPM of Product); big → ≥5 across lines.** Names from
Hunter, ranked by title; uncertain emails verified, invalid ones dropped before
they reach the sheet. Rows land in **Networking** as PROSPECT with `job_open` Y/N.

**Step 6 · Research + note drafting — 9:15am, automatic** (scheduled Claude session;
manual: "write the note for X")
Finds 5–10 new target companies by the criteria (supply-demand, auctions,
conversion economics, attribution, ops enablement — open roles preferred, not
required; adds the best 2–3 to manual targets). Then for each queued row with an
empty draft, follows the `networking-note` skill: their product → fresh
observation → one story-bank story with a verbatim metric → the ask. 4 bullets.
Writes into **Referrals.`note_to_send`** / **Networking.`draft_body`**, hook in
`personalization_hook`. Runs while the desktop app is open; catches up on launch.

**Step 7 · The send block — Juhi, ~20 min/day**
Open Referrals (sort by `first_degree_available`) and Networking (today's
`due_date`). Read the draft, personalize the last 10%, send from your own
browser/email. Then mark it: Referrals → date into `sent_1`/`sent_2`/`sent_rec`;
Networking → `status` SENT, `sent_date`, tick `personalized`. Telling Claude
"note sent to X" does the bookkeeping and bumps the story's use count.

**Step 8 · Follow-ups — with the 9am run** (manual: `python3 outreach_tracker.py`)
`followup_due` = earliest send + 7 days; unanswered sends flagged, answered ones
cleared; queued connection requests beyond 15/week put on HELD; sends without the
personalization tick reported. DMs and email are uncapped — only new connection
requests count.

## What runs when

| Time | What | Where |
|---|---|---|
| 5:00am | discovery | GitHub Actions |
| 9:00am | referral match + networking queue + follow-ups | GitHub Actions |
| 9:15am | target research + note drafting | scheduled Claude session (app open) |
| Juhi's call | scoring (~$0.006/job) | her terminal |
| Juhi's block | personalize + send + mark | her browser |

## Costs

Fixed: $0 (all free tiers). Scoring: ~$5.50 per ~1,000-job backfill, ~25¢/day
incremental. Hunter: free plan (50 searches + 100 verifications/mo) covers ~2 weeks
of cadence; Starter $49/mo only for months of active cold email. Research and note
drafting: subscription, no API spend.

## Guardrails

Human sends everything · no automation against LinkedIn · 15 connection
requests/week enforced · fuzzy matches never auto-fill · every draft needs a
target-specific hook · story rotation (never the same story twice in a week) ·
blocked companies (Moloco) surface nowhere · scored rows and sent rows are never
overwritten by any script.

## Still missing / known gaps

1. **HUNTER_API_KEY as a GitHub secret** — until Juhi adds it (repo → Settings →
   Secrets → Actions), the 9am cloud run emits search links instead of named
   humans; local runs are fine.
2. **Cross-source duplicate roles** — the same job from two sources gets two rows
   (different `job_id`s), e.g. TEGNA, Walmart. Cosmetic; skip the twin. Fix: a
   title+company dedupe pass.
3. **Ashby/Lever fetchers** — ~11 companies listed in `target_companies.json` are
   never fetched (Rippling, Cohere, Perplexity, Retool, Uber…).
4. **Alias curation** — `python3 contacts_ingest.py --report-unmatched` lists big
   contact clusters; 15 min on `company_aliases.json` (e.g. "jpmorganchase" →
   "JPMorgan Chase") buys real referral matches.
5. **VC-portfolio jobs are unscoreable** (source sends no descriptions) — marked in
   the sheet, invisible to matching.
6. **Scoring not scheduled** — deliberate (it spends money). ~50¢/day would close
   the loop; needs Juhi's call.
