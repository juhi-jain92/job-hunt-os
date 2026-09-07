# Job Hunt OS

A referral and networking engine for a PM job search. Every morning it finds
new roles, scores them against Juhi's resume, matches the 7+ ones to people she
already knows, queues cold prospects at target companies, and drafts the notes.
Every note is sent by a human. Nothing is ever auto-sent.

**One command runs everything:**

```bash
python3 daily.py
```

It runs itself at 12:30 UTC (5:30am PDT, 4:30am PST) via GitHub Actions. The output of a good
morning is the **Today** tab in the "Job Hunt OS" Google Sheet: up to 5 rows per lane (referral, networking),
each with a named person, a link, and a draft — the 20-minute send block.

## The daily routine (Juhi)

1. Open the **Today** tab. Up to ten rows, drafts in hand.
2. Personalize the last 10%, send from your own LinkedIn / email.
3. Mark it: Referrals → today's date in `sent_1`; Networking → `status` SENT + `sent_date`.
4. Done. Tomorrow's rows are drafted by the time you wake up.

Everything else in the sheet is machinery. You never need to open it.

## What runs, in order

| Stage | Script | Writes to | Cost |
|---|---|---|---|
| Discover roles (JSearch, Greenhouse, Wellfound, VC boards) | `job_search.py` | Sheet1 | free |
| Prune ledger rows older than 7 days (yours are kept; full copy parked in a hidden `ledger_backup` tab) | `prune_ledger.py` | Sheet1 | free |
| Score each new role 0–10 vs resume key details (Sonnet 5, capped 100/run) | `match_scorer.py` | Sheet1 | ~0.6¢/job |
| Match 7+ roles to warm contacts (2 referrers + recruiter per role) | `referral_match.py` | Referrals | free |
| Queue cold prospects: 5 company/team slots a day, product leaders only, Hunter-verified emails | `networking_daily.py` | Networking | Hunter (paid) |
| Draft up to 5 notes per lane: fresh web-searched hook + one story-bank story, validated in Python | `draft_notes.py` | Referrals / Networking | ~6¢/draft |
| Follow-ups, weekly connect count, stale flags | `outreach_tracker.py` | both | free |
| The Today view, up to 5 rows per lane | `today.py` | Today | free |

Total: roughly **$1 a day at the caps** (100 scored roles + 10 drafts); most days less. Details, decisions, and gaps: [docs/architecture.md](docs/architecture.md).
Target companies and why: [docs/targets.md](docs/targets.md).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env            # RAPIDAPI_KEY, APIFY_TOKEN, ANTHROPIC_API_KEY, HUNTER_API_KEY
# credentials/sheets_key.json   — Google service-account key
# config/context_store.json     — personal preferences (template provided)
# data/connections/*.csv        — LinkedIn exports; python3 contacts_ingest.py
```

GitHub Actions needs the same four keys plus `GOOGLE_SHEETS_KEY` (base64 of the
service-account JSON) as repository secrets.

## Guardrails

Human sends everything · no automation against LinkedIn · 15 connection
requests/week · fuzzy company matches never auto-fill · every draft needs a
target-specific hook · no story reused within a week · blocked companies never
surface · sent rows are never overwritten.
