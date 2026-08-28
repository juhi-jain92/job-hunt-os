# Discovery

Stage 1 of Job Hunt OS: fetch → normalize → dedupe → title-filter → append to the ledger.
No model calls, no cost. One command, idempotent — re-running adds only unseen jobs.

```bash
python3 job_search.py
```

## Sources

Each source is a module returning the same schema. A failed source returns `[]` with a
warning — one dead source never stops the run.

| Source | Module | Auth | Typical yield | Notes |
|---|---|---|---|---|
| JSearch | `job_search.py` | `RAPIDAPI_KEY` | ~680 | 18 queries × 5 pages = 18 requests of a 10k/mo quota. `date_posted_filter: "week"` applied server-side. Timeouts retry once; other errors don't. |
| Greenhouse | `greenhouse_sources.py` | none | ~420 | 39 company boards from `target_companies.json`, fetched 8 at a time. Whole board is pulled, then title-filtered. |
| Wellfound | `apify_sources.py` | `APIFY_TOKEN` | ~50 | Third-party actor; costs credits; occasionally flaky. |
| VC portfolios | `apify_sources.py` | `APIFY_TOKEN` | ~30 | a16z/YC/Sequoia. **Returns no descriptions** — these rows are marked "low match / no description" without a model call. |

## Schema — the ledger's 13 columns

```
job_id | title | company | location | source | posted_at |
score | ai_score | adtech_score | status | notes | url | description
```

Discovery writes the first six plus `url` and `description` (truncated to 8,000 chars),
seeds `status = "new"`, and leaves the scoring columns blank. The scorer fills
`score` (0–10 total — everything downstream gates on `score >= 7`), the two dimension
scores, and `notes` (track, resume, reason as prose).

`job_id` is the dedupe key: native from JSearch, `gh_{slug}_{id}` from Greenhouse,
`wf_{id}` from Wellfound, an md5 of URL+title for VC jobs. URL-derived ids drift when a
posting is edited — accepted, since fuzzy dedupe risks collapsing distinct roles.

## Gates

1. **In-memory dedupe** by `job_id` as sources are merged; first source wins (JSearch runs first).
2. **Title filter** — keep if any of the 19 `title_filter_terms` appears in the lowercased
   title. Drops ~190 of ~1,180. Cheap gate before the ~$0.012/job scoring gate. Title-only,
   so an oddly-titled PM role is lost silently.
3. **Sheet-level dedupe** — `append_new_jobs` re-checks ids against column A. Append-only:
   discovery never updates an existing row, so scored/user-edited rows are untouchable.

## Changes in this revision

- **Schema slimmed 17 → 13 columns.** Deleted `remote`, `salary_text`, `match_flag`,
  `recommended_track` (tier), `cover_letter`. Tier is gone everywhere: the scorer now
  writes the numeric `score` and the referral lane gates on the number directly —
  an A/B showed the model mislabeled its own tier ~1/3 of the time, so the label is
  computed nowhere and stored nowhere.
- **`config/filters.py` deleted** (`detect_remote` had no remaining callers) along with
  two dead single-cell write helpers in `sheets.py`.
- **Score writes are column-name driven** (`COL_INDEX`), so reordering columns can't
  silently write into the wrong cell the way the old hardcoded `J:M` ranges could.
- **Greenhouse fetches 8 boards concurrently** (was 39 sequential calls at 0.5s apart) —
  discovery now runs ~1–2 min instead of ~4.
- **Unscoreable rows are marked, not sent** — empty rows and no-description VC jobs are
  flagged in the sheet without spending an API call.

## Health check

Compare the end-of-run per-source counts against the yields above.

| Symptom | Cause |
|---|---|
| JSearch near zero | `RAPIDAPI_KEY` expired / quota out |
| A Greenhouse slug 404s | Company left Greenhouse — remove from `target_companies.json` |
| Apify warning | Actor flaked; ignore unless persistent |
| Pre-filter drops nearly all | `title_filter_terms` edited badly |

Automation: `.github/workflows/daily_job_search.yml` runs discovery daily at 5am PT.
Scoring stays a deliberate local action (`caffeinate -dims python3 match_scorer.py`).

## Known gaps

1. Ashby/Lever companies listed in `target_companies.json` are **not fetched** — no
   fetcher exists (Ironclad, Rippling, Cohere, Perplexity, Retool, Uber, +5).
2. VC portfolio jobs can't be scored (no descriptions) — fetch separately or drop the source.
3. Title filter loses unusually-titled PM roles, uncounted.
