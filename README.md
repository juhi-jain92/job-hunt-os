# Job Hunt OS

A referral and networking engine for a PM job search. Every morning it finds
new roles, scores them against Juhi's resume, matches the 7+ ones to people she
already knows, queues cold prospects at target companies, and drafts the notes.
Every note is sent by a human. Nothing is ever auto-sent.

**One command runs everything:**

```bash
python3 daily.py
```

It runs itself at 12:30 UTC (5:30am PDT, 4:30am PST) via GitHub Actions. The
output of a good morning is the **Today** tab in the "Job Hunt OS" Google Sheet:
every role and prospect that has a draft and has not been sent, best first, each
with the job link, the person, and the note — the 20-minute send block.

## The daily routine (Juhi)

1. Open the **Today** tab. Rows with drafts already in hand.
2. Open the job link to see what the role is; personalize the last 10%; send it
   from your own LinkedIn or email.
3. Type anything in the `sent` column, right there in Today.
4. Done. The next run files that mark back to its source row, drops it out of
   the view, and has tomorrow's rows drafted by the time you wake up.

Everything else in the sheet is machinery. You never need to open it.

## What runs, in order

| Stage | Module | Writes to | Cost |
|---|---|---|---|
| File anything you marked `sent` in Today back to its source row | `stages/today.py --absorb-only` | Referrals / Networking | free |
| Discover roles (JSearch, 106 boards across Greenhouse/Ashby/Lever, Wellfound, VC portfolios) | `stages/job_search.py` | Jobs | free |
| Prune roles older than 7 days (yours are kept; full copy parked in a hidden `ledger_backup` tab) | `stages/prune_ledger.py` | Jobs | free |
| Score each new role 0–10 vs resume key details (Sonnet 5, capped 100/run) | `stages/match_scorer.py` | Jobs | ~0.6¢/job |
| Rebuild the referral lane: qualifying roles only, one row per role, 2 referrers + recruiter each | `stages/referral_match.py` | Referrals | free |
| Queue cold prospects: 5 company/team slots a day, product leaders only, Hunter-verified emails | `stages/networking_daily.py` | Networking | Hunter (paid) |
| Draft up to 5 notes per lane: fresh web-searched hook + one story-bank story, validated in Python | `stages/draft_notes.py` | Referrals / Networking | ~6¢/draft |
| Follow-ups, weekly connect count, stale flags | `stages/outreach_tracker.py` | both | free |
| Rebuild the Today view: every drafted, unsent row, best first | `stages/today.py` | Today | free |

Total: roughly **$1 a day at the caps** (100 scored roles + 10 drafts); most days
less. Details, decisions, and gaps: [docs/architecture.md](docs/architecture.md).
Target companies and why: [docs/targets.md](docs/targets.md).

## Layout

```
job-hunt-os/
├── daily.py            the orchestrator — the only thing you run
├── stages/             the nine pipeline stages, in run order
├── lib/                shared code the stages import
│   ├── sheets.py             all Google Sheets read/write
│   ├── normalize.py          company-name and title normalization, blocklist
│   ├── contact_extract.py    Hunter.io lookups and email verification
│   ├── linkedin_urls.py      search-link builders (no automation)
│   ├── greenhouse_sources.py Greenhouse public boards
│   ├── ats_sources.py        Ashby + Lever public boards
│   └── apify_sources.py      Wellfound and VC-portfolio scrapers
├── tools/              manual, occasional
│   └── contacts_ingest.py    import a fresh LinkedIn connections export
├── config/             what you tune: targets, search terms, preferences
├── docs/               architecture, target research, PRD
└── resume/             story bank and resume (gitignored, never leaves this machine)
```

Stages run as modules so the repo root stays on the import path:

```bash
python3 -m stages.match_scorer --estimate
python3 -m stages.networking_daily --dry-run
python3 -m stages.today --print
python3 daily.py --no-spend        # whole pipeline, skipping the two stages that spend
python3 daily.py --from draft      # resume partway: marks|discover|prune|score|match|network|draft|track|today
```

## What you tune

| File | What it holds |
|---|---|
| `config/target_companies.json` | Job boards to watch (`greenhouse_slugs`, `ashby_slugs`, `lever_slugs`), hand-picked targets, blocked companies |
| `config/company_meta.json` | Email domain per company, so Hunter can find real names |
| `config/search_config.json` | Search queries, title filters, model and effort settings |
| `config/context_store.json` | Your preferences: locations, comp floor, seniority band (gitignored) |
| `config/story_digest.json` | Compacted story bank the drafter picks from (rebuild with `--refresh-digest`) |

The scoring rubric and the resume key details live in `stages/match_scorer.py`;
the note recipe lives in `stages/draft_notes.py`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env            # RAPIDAPI_KEY, APIFY_TOKEN, ANTHROPIC_API_KEY, HUNTER_API_KEY
# credentials/sheets_key.json   — Google service-account key
# config/context_store.json     — personal preferences (template provided)
# data/connections/*.csv        — LinkedIn exports; python3 -m tools.contacts_ingest
```

GitHub Actions needs the same four keys plus `GOOGLE_SHEETS_KEY` (base64 of the
service-account JSON) as repository secrets.

## What keeps the lanes honest

The Referrals and Networking tabs used to only ever grow. They now rebuild
themselves every run, so what you see is what is worth doing today:

- **One row per role**, not per posting. The same job arrives from several
  sources under different ids; they collapse into one.
- **Dealbreakers never appear.** A role can score 9 on fit and still be a
  staffing agency, under the comp floor, or onsite somewhere you will not move.
  Those are excluded, not shown with a warning.
- **Seniority is a hard gate.** A posting with no seniority marker in its title
  never reaches the referral lane, however well the domain fits.
- **Nothing you touched is ever dropped.** A row you marked sent survives even
  when the role stops qualifying.
- **Nameless prospects expire.** A networking row nobody could put a name to
  can never be drafted, so it clears after two days instead of piling up.

## Guardrails

Human sends everything · no automation against LinkedIn · connection requests
counted weekly against a 15 target · fuzzy company matches never auto-fill ·
every draft needs a target-specific hook and a verbatim metric · no story reused
within a week · blocked companies never surface · scored and sent rows are never
overwritten · the ledger tab is resolved by name and refuses to write into any
tab that is not the ledger.
