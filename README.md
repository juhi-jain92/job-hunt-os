# Job Hunt OS

A personal agentic job search pipeline. Discovers roles across multiple sources daily, scores them against your criteria using an LLM, and surfaces the best ones for manual review.

Built by [Juhi Jain](https://www.linkedin.com/in/juhi-jain-4024a7104/), AI PM — as a portfolio project and a real tool used actively in a job search.

> Read the full builder story: [docs/builder-story-final.md](docs/builder-story-final.md)
> Read the technical learnings: [docs/technical-learnings.md](docs/technical-learnings.md)

---

## What It Does

**Skill 1: Job Discovery (`job_search.py`)**
Pulls jobs from four sources, deduplicates by job_id, pre-filters by your target titles, and appends new rows to a Google Sheet. Runs daily via GitHub Actions.

**Skill 2: LLM Match Scorer (`match_scorer.py`)**
Reads unscored rows from the sheet, sends each JD plus your candidate profile to an LLM, scores against a rubric, and writes scores back. Run manually when you want to score a batch.

**Human Gate**
You review the scored sheet, set status flags, and decide what to apply to. Nothing goes out without your decision.

---

## Architecture

```
job_search.py (daily cron)
├── JSearch (RapidAPI)        → LinkedIn, Indeed, ZipRecruiter, Glassdoor
├── Apify Wellfound Scraper   → startup and AI-first companies
├── Apify VC Portfolio        → a16z, YC, Sequoia portfolio companies
└── Greenhouse Public API     → hand-picked target companies

       ↓ deduplicate by job_id
       ↓ filter by title_filter_terms
       ↓ append-only write to Google Sheet

match_scorer.py (manual)
└── reads unscored rows
└── sends JD + candidate profile to LLM
└── writes score, tier, track, reason back to sheet

You → review sheet → decide → apply
```

---

## Prerequisites

- Python 3.10+ (3.11+ recommended)
- A Google Cloud project with Sheets API and Drive API enabled
- A Google service account JSON key file
- API keys for: RapidAPI (JSearch), Apify, and your chosen LLM provider

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/juhi-jain92/job-hunt-os.git
cd job-hunt-os
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set up API keys

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys. For the LLM scorer, only fill in the key for your chosen provider (see step 5):

```
RAPIDAPI_KEY=your_rapidapi_key
APIFY_TOKEN=your_apify_token
GOOGLE_SHEET_OWNER_EMAIL=your@email.com

# Fill in only the one matching scorer_settings.provider in search_config.json:
ANTHROPIC_API_KEY=your_anthropic_api_key   # provider = "anthropic"
OPENAI_API_KEY=your_openai_api_key         # provider = "openai"
ZAI_API_KEY=your_zhipuai_api_key           # provider = "zhipuai"
```

**Getting each key:**
- RapidAPI (JSearch): [rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) — Pro tier, $25/month, 10k requests included
- Apify: [console.apify.com/account/integrations](https://console.apify.com/account/integrations) — pay per use, ~$0.10–0.20 per run
- Anthropic: [console.anthropic.com/account/keys](https://console.anthropic.com/account/keys)
- OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- ZhipuAI: [bigmodel.cn](https://bigmodel.cn) → API Keys

### 4. Set up Google Sheets access

The pipeline writes results to a Google Sheet via a service account.

**4a. Create a Google Cloud project and enable APIs**

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project
2. Go to **APIs & Services → Library** and enable both:
   - **Google Sheets API**
   - **Google Drive API**

**4b. Create a service account**

1. Go to **IAM & Admin → Service Accounts → Create Service Account**
2. Give it any name (e.g. `job-hunt-os`)
3. Skip the optional role/user access steps — no project-level IAM role is needed
4. Open the service account, go to **Keys → Add Key → Create new key → JSON**
5. Download the JSON file

**4c. Save the key**

```bash
mkdir -p credentials
mv ~/Downloads/your-key-file.json credentials/sheets_key.json
```

The `credentials/` directory is gitignored — this file is never pushed to GitHub.

**4d. First run creates and shares the sheet**

The first time you run `job_search.py`, it will automatically:
- Create a Google Sheet named **"Job Hunt OS"**
- Share it with editor access to the email in `GOOGLE_SHEET_OWNER_EMAIL`

You'll find the sheet in your Google Drive after the first run.

### 5. Configure for your role

**Edit `config/search_config.json`** — controls what roles to discover and which LLM to score with:

```json
{
  "search_queries": [
    "Senior Product Manager",
    "AI Product Manager",
    "Staff Product Manager"
  ],
  "title_filter_terms": [
    "product manager",
    "product lead",
    "ai pm"
  ],
  "scorer_settings": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-6",
    "note": "Set provider to 'anthropic', 'openai', or 'zhipuai'. Model must match the provider."
  }
}
```

- `search_queries` — fed to JSearch; use role titles you'd search on LinkedIn
- `title_filter_terms` — post-filter applied to all sources; any job whose title contains one of these strings passes through
- `scorer_settings.provider` — which LLM to score with (see [Swapping the LLM](#swapping-the-llm))

**Edit `config/target_companies.json`** — Greenhouse slugs for companies you want to monitor directly (bypasses JSearch). Find a company's slug by visiting `boards.greenhouse.io/{slug}` — e.g. `boards.greenhouse.io/stripe` → slug is `stripe`.

### 6. Set up your candidate profile

```bash
cp config/context_store.template.json config/context_store.json
```

Edit `config/context_store.json` with your personal details:

| Section | What to fill in |
|---|---|
| `candidate` | Name, location, YOE, current status |
| `shared` | Location preferences, remote preference, salary floor/target, seniority band |
| `company_profile` | Target company stage, companies to avoid, dream tier list |
| `tracks` | One entry per job track — positioning, target roles, must-have signals, dealbreakers, and `resume_path` |

This file is gitignored and never pushed to GitHub.

**Tracks** are how the scorer compares your profile to a JD. Each track represents a different resume/positioning angle (e.g. AI PM track vs. Adtech PM track). You can configure one or two tracks. Each track needs a `resume_path` pointing to a markdown file:

```json
"tracks": {
  "ai": {
    "track_label": "AI PM",
    "resume_path": "resume/resume_ai.md",
    "positioning": "...",
    "target_roles": ["AI Product Manager", "..."],
    "must_have_signals": ["LLM", "agent", "AI"],
    "boost_signals": ["RAG", "evals", "inference"],
    "dealbreakers": ["AI is marketing-only", "..."]
  }
}
```

Create the resume markdown files referenced by `resume_path`. The `resume/` directory is gitignored.

### 7. (Optional) Add a scoring rubric

The scorer loads `config/job_fit_eval_framework.md` if it exists — this is your custom rubric that the LLM uses to calibrate scores. If the file is missing, the scorer falls back to built-in guardrails (still works, just less tailored).

This file is gitignored. To create one, write a markdown document describing your scoring philosophy: what makes a Tier 1 vs Tier 3 role for your situation, domain signals that matter, red flags, etc.

---

## Running It

### Job Discovery

```bash
python3 job_search.py
```

Fetches jobs from all four sources, deduplicates, filters by your title terms, and appends new rows to the sheet. Safe to run multiple times — existing `job_id`s are never duplicated.

### LLM Match Scorer

```bash
# Dry run: score 5 jobs, print raw JSON, do NOT write to sheet
python3 match_scorer.py --preview 5

# Score a small batch first to check calibration
python3 match_scorer.py --limit 10

# Score everything unscored (use caffeinate on Mac to prevent sleep)
caffeinate -dims python3 match_scorer.py
```

The scorer skips rows that already have scores and rows with user-owned statuses (`applied`, `interviewing`, `rejected`, `skipped`). It's safe to interrupt and re-run — it resumes automatically.

**Estimate cost before a large run (Anthropic only):**
```bash
python3 match_scorer.py --estimate
```

---

## Scoring Output

Each job is scored across four dimensions:

| Dimension | Max Points | What it measures |
|---|---|---|
| Domain Match | 3 | How well the role's domain fits your target |
| AI Readiness | 3 | How AI-core the role is |
| Skills Match | 2 | Hard skill overlap with JD |
| Level & Scope | 2 | Seniority and scope fit |
| **Total** | **10** | |

| Tier | Score | What to do |
|---|---|---|
| Tier 1 | 9–10 | Full effort — tailor resume, write cover letter, seek referral |
| Tier 2 | 7–8 | Apply — tailored resume, standard cover letter |
| Tier 3 | 5–6 | Spray — minimal tailoring, apply quickly |
| Skip | below 5 | Don't apply |

Hard skips override tier — sales/revenue/account management roles, solutions-heavy roles, and agencies are auto-skipped regardless of score.

The sheet columns written per job:

| Column | Value |
|---|---|
| `ai_score` | AI Readiness dimension score (0–3) |
| `domain_score` | Domain Match dimension score (0–3) |
| `match_flag` | Track label or "DUAL" or "LOW MATCH" |
| `recommended_track` | `"Tier X \| TRACK"` |
| `status` | Auto-set to `ready to apply`, `spray`, or `low match` |
| `notes` | 2–3 sentence explanation from the LLM |

---

## Swapping the LLM

Change `provider` and `model` in `config/search_config.json` — no code changes needed:

```json
"scorer_settings": {
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001"
}
```

Supported providers out of the box:

| `provider` | Key in `.env` | Default model | Notes |
|---|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | Enables `--estimate`. Haiku is cheapest. |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` | `gpt-4o-mini` is cheapest. |
| `zhipuai` | `ZAI_API_KEY` | `glm-4-flash` | `glm-4-flash` is cheapest. |

**Benchmarking tip:** run two providers on the same 50-job batch and compare tier/track agreement. If agreement is ≥90%, use the cheaper model for all batch runs.

To add a new provider, add a `_raw_<provider>` function in `match_scorer.py` following the same pattern as the existing three, then register it in the `_callers` dict inside `_call_llm`.

---

## Automating Discovery with GitHub Actions

The daily cron runs `job_search.py` automatically at 1 PM UTC. To activate it:

**1. Add these secrets to your GitHub repo** (Settings → Secrets and variables → Actions):

| Secret | Required? | Value |
|---|---|---|
| `RAPIDAPI_KEY` | Yes | your RapidAPI key |
| `APIFY_TOKEN` | Yes | your Apify token |
| `GOOGLE_SHEETS_KEY` | Yes | base64-encoded `credentials/sheets_key.json` |
| `GOOGLE_SHEET_OWNER_EMAIL` | Yes | email that gets editor access to the sheet |
| `ANTHROPIC_API_KEY` | If using Anthropic | your Anthropic key |
| `OPENAI_API_KEY` | If using OpenAI | your OpenAI key |
| `ZAI_API_KEY` | If using ZhipuAI | your ZhipuAI key |

To base64 encode your service account key:
```bash
base64 -i credentials/sheets_key.json | pbcopy   # Mac — copies to clipboard
```

**2. The workflow file is already in the repo** at `.github/workflows/daily_job_search.yml` — no changes needed.

**3. Test before relying on the cron:**

Go to GitHub → Actions → Daily Job Discovery → Run workflow to trigger manually and confirm it works.

---

## Running Costs

| Component | Cost |
|---|---|
| JSearch API (Pro tier) | $25/month flat, 10k requests included |
| Apify actors | ~$0.10–0.20 per discovery run |
| Greenhouse API | Free, no auth required |
| Google Sheets API | Free |
| LLM scoring (initial batch ~700 jobs) | varies by provider — see pricing pages |
| LLM scoring (ongoing, manual chat) | ~$0 — paste new jobs into any LLM chat |
| **Daily discovery only** | **~$0.10–0.20/run** |

**Recommended approach:** run the batch scorer once for the initial backlog, then score new daily jobs manually by pasting them into any LLM chat. At 20–50 new jobs per day, manual scoring is faster and costs nothing.

---

## Known Limitations

- JSearch returns partial descriptions (~500 chars) on some listings — Greenhouse returns full JDs
- VC Portfolio actor returns no job descriptions — these score on title and company only
- Remote detection is text-based — reliable for JSearch and Greenhouse, less reliable for VC Portfolio
- `batch_write_scores` in `sheets.py` uses hardcoded column letters — will break if you add columns in the middle of the schema. Always add new columns at the end of `COLUMNS`.
- Python 3.9 is past end of life — upgrade to 3.11+ recommended

---

## Repo Structure

```
job-hunt-os/
├── config/
│   ├── search_config.json           ← edit this for your role + LLM provider
│   ├── context_store.template.json  ← copy to context_store.json and fill in
│   ├── context_store.json           ← gitignored, your private profile
│   ├── job_fit_eval_framework.md    ← gitignored, optional custom scoring rubric
│   ├── filters.py                   ← remote detection logic
│   └── target_companies.json        ← Greenhouse company slugs to monitor
├── resume/                          ← gitignored, add your markdown resume files here
├── credentials/                     ← gitignored, add your service account key here
├── docs/
│   ├── builder-story-final.md       ← why and how this was built
│   └── technical-learnings.md      ← technical decisions and bugs
├── .github/workflows/
│   └── daily_job_search.yml         ← GitHub Actions cron for job discovery
├── job_search.py                    ← discovery orchestrator
├── apify_sources.py                 ← Wellfound + VC portfolio scrapers
├── greenhouse_sources.py            ← target company Greenhouse boards
├── match_scorer.py                  ← LLM scoring pipeline
├── sheets.py                        ← Google Sheets read/write
├── .env.example                     ← copy to .env and fill in
└── requirements.txt
```

---

## Built With

Python, Anthropic / OpenAI / ZhipuAI APIs (configurable), Google Sheets API, JSearch (RapidAPI), Apify, Greenhouse public API, GitHub Actions.

---

*Built by [Juhi Jain](https://www.linkedin.com/in/juhi-jain-4024a7104/) — AI PM building in public.*
