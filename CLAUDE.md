# CLAUDE.md

> `AGENTS.md` is the OpenCode equivalent of this file. Keep both in sync when updating AI assistant instructions.

## Commands
- Set up Python locally with `python3 -m venv .venv`, `source .venv/bin/activate`, then `pip install -r requirements.txt`.
- Run discovery with `python3 job_search.py`; it fetches jobs and appends only new `job_id`s to the Google Sheet.
- Run scorer safely with `python3 match_scorer.py --preview 5` first; preview prints model JSON and does not write to the sheet.
- Score a small batch with `python3 match_scorer.py --limit 10`; for full local scoring on macOS use `caffeinate -dims python3 match_scorer.py`.
- There is no configured test/lint suite. For basic verification use `python3 -m py_compile *.py config/*.py`, plus a preview/limited run only when credentials and API keys are available.

## Architecture
- `job_search.py` is the discovery orchestrator: JSearch, Apify sources, and Greenhouse are normalized, deduped by `job_id`, filtered by `config/search_config.json` `title_filter_terms`, then appended to Sheets.
- `match_scorer.py` reads unscored sheet rows, builds a candidate/job prompt from private local context, calls the configured LLM provider, and batch-writes scores every 25 jobs.
- `sheets.py` owns the single spreadsheet schema and all Google Sheets reads/writes; adapters should return dicts matching its `COLUMNS`.
- Source adapters: `apify_sources.py` handles Wellfound and VC portfolio actors, `greenhouse_sources.py` handles target company Greenhouse boards, and `config/filters.py` contains text-based remote detection.

## Config And Secrets
- Do not read or expose private local inputs unless explicitly asked: `.env`, `credentials/`, `resume/`, and `config/context_store.json` are gitignored for a reason.
- LLM provider is set in `config/search_config.json` → `scorer_settings.provider` (`"anthropic"`, `"openai"`, or `"zhipuai"`). Set the matching API key in `.env`. The scorer validates only the key for the active provider at startup.
- For ZhipuAI GLM calls, keep `thinking={"type": "disabled"}` — omitting it causes `finish_reason=length` which returns empty `message.content`.
- `credentials/sheets_key.json` must exist locally for Sheets access; the created sheet is named `"Job Hunt OS"` and is shared to `GOOGLE_SHEET_OWNER_EMAIL` (required — no default).
- `config/search_config.json` is committed operational config: role queries, title filters, Apify scraper settings, and scorer model. `config/context_store.json` is the private candidate profile copied from `config/context_store.template.json`.
- Apify scraper targeting is configured in `config/search_config.json` → `apify_settings` (not hardcoded in `apify_sources.py`).

## Data And Sheet Gotchas
- The pipeline is append-only ledger mode: discovery skips existing `job_id`s, and the scorer skips rows with user-owned statuses `applied`, `interviewing`, `rejected`, or `skipped`.
- `sheets.batch_write_scores()` uses hardcoded Google Sheet ranges (`J:M`, `O`, `P`). If changing `sheets.COLUMNS`, add new columns at the end or update the ranges at the same time.
- Keep `description` as the last sheet column; prior bugs silently scored rows without descriptions when schema and writes diverged.
- Remote status is derived from title/location/description text, not trusted API booleans.

## Source Quirks
- JSearch uses RapidAPI `search-v2`, returns partial descriptions on some listings, and `num_pages=5` counts as one request per query.
- Greenhouse uses the public API with no auth and `content=true`; slugs live in `config/target_companies.json`, and some companies listed there are intentionally noted as Ashby/Lever instead.
- Apify VC portfolio jobs have no descriptions, so they score on title/company only. Wellfound uses `enrichDetail=True` for full descriptions and may fail non-fatally.

## GitHub Actions
- `.github/workflows/daily_job_search.yml` runs discovery only (`job_search.py`) on Python 3.11 at `0 13 * * *` UTC plus manual dispatch.
- The workflow writes `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `ZAI_API_KEY` to `.env` — only the one matching `scorer_settings.provider` needs to be set as a repo secret.
