# Discovery — How Jobs Get Into the System

**Stage 1 of Job Hunt OS.** Everything downstream — scoring, referrals, networking — reads
what this stage produces. Nothing here calls a model; discovery is pure fetch, normalize,
filter, append.

Last verified against a live run: 2026-08-27 (990 jobs written).

---

## The shape of it

```
 4 sources ──▶ normalize ──▶ dedupe ──▶ title filter ──▶ ledger
   fan out      one schema    by id      cheap gate      append-only
```

One command runs the whole stage:

```bash
python3 job_search.py
```

It is idempotent. Run it twice and the second run adds nothing, because every job carries a
stable id and the ledger rejects ids it already holds.

---

## 1. The four sources

Each source is a separate module returning a list of dicts in one shared schema. A source
that fails returns `[]` and prints a warning — **one dead source never stops the run.**
That single decision is why a run still completed the day Wellfound's actor timed out.

| Source | Module | What it reaches | Auth | Typical yield |
|---|---|---|---|---|
| **JSearch** | `job_search.py` | Aggregator over LinkedIn, Indeed, ZipRecruiter, Glassdoor and ~70 job boards | `RAPIDAPI_KEY` | ~680 |
| **Greenhouse** | `greenhouse_sources.py` | 39 named companies' public boards | none | ~420 of ~7,500 |
| **Wellfound** | `apify_sources.py` | Startup roles, remote + Seattle | `APIFY_TOKEN` | ~50 |
| **VC portfolios** | `apify_sources.py` | a16z, YC, Sequoia portfolio companies | `APIFY_TOKEN` | ~30 |

### JSearch — breadth

Runs each of the 18 queries in `config/search_config.json` at `num_pages=5`, which returns
up to 50 results while counting as **one** API request. Eighteen queries therefore cost 18
requests out of a 10,000/month quota — the budget is not the constraint, so queries can be
added freely.

`date_posted_filter` (currently `"week"`) is applied server-side by JSearch. Widening it to
`"month"` roughly quadruples volume and mostly returns roles already seen, which is why it
was narrowed.

Retry policy is deliberately asymmetric: a **timeout** retries once after 10s, any other
request error does not retry at all. A timeout is usually transient; a 403 or a 429 will
just fail again and waste quota.

### Greenhouse — precision

Hits `boards-api.greenhouse.io` directly for 39 company slugs in
`config/target_companies.json`. No auth, no quota, no cost.

This source has the worst raw ratio — ~7,500 jobs fetched to find ~420 PM roles, because it
pulls each company's *entire* board — and the best relevance, because you chose the
companies. It also has the richest side-effect: the same API exposes each company's
department structure, which the networking lane later uses as a product-line map.

`config/target_companies.json` also records companies on Ashby and Lever under
`_not_on_greenhouse`. Those are **not** fetched — no fetcher exists for either platform yet.

### Apify actors — the fragile edge

Two third-party scrapers run synchronously via `run-sync-get-dataset-items`, with an HTTP
timeout set 15s longer than the actor's own so the actor's error surfaces instead of a bare
connection reset.

These are the least reliable sources: third-party actors change output shape without notice.
They are also the only ones that cost per-run credits. Treat any Apify warning as normal
operation, not an incident.

**Known gap:** the VC portfolio actor returns no job descriptions. Those rows arrive with
`description: ""`, and the scorer cannot judge a role it cannot read — they score near zero
regardless of merit. Roughly 30 jobs per run are effectively invisible to scoring.

---

## 2. One schema, four shapes

Every source normalizes into the same dict before anything else touches it. This is the
contract that lets the rest of the stage stay simple:

```python
{
  "job_id":      str,          # stable and unique — the dedupe key
  "title":       str,
  "company":     str,
  "location":    str,
  "remote":      str,          # remote | hybrid | onsite, from config/filters.py
  "salary_text":  str | None,   # pre-formatted, e.g. "$180,000–$220,000 YEAR"
  "url":         str,
  "description": str,          # truncated to 8,000 chars
  "source":      str,
  "posted_at":   str,
}
```

### Where `job_id` comes from

Dedupe is only as good as this field, and the four sources do not agree on identity:

| Source | id strategy |
|---|---|
| JSearch | native `job_id` (an opaque base64 blob) |
| Greenhouse | `gh_{slug}_{numeric_id}` |
| Wellfound | `wf_{native_id}`, falling back to a hash of the portal URL |
| VC portfolios | `vc_{md5(apply_url + title)[:12]}` — no native id exists |

The synthesized ids are stable across runs *as long as the underlying URL is stable*. When a
company edits a posting's URL, the same job reappears under a new id. This is the main
source of duplicate rows, and it is accepted rather than solved — the alternative is fuzzy
title-and-company matching, which risks collapsing two genuinely different roles at one
company.

### Salary and location are formatted at the edge

Each source formats its own `salary_text` and `location` string because each returns a
different shape — JSearch gives `min/max/period`, Wellfound gives `min/max/currency`,
Greenhouse gives nothing. Normalizing early means nothing downstream ever parses salary.

---

## 3. Dedupe

A single in-memory `seen_ids` set, checked as each job is appended. First occurrence wins,
so **source order is precedence**: JSearch runs first, so when a role appears both on an
aggregator and on the company's own Greenhouse board, the aggregator's copy is kept.

That is arguably backwards — the Greenhouse copy has a cleaner description and a direct
apply URL — but the ids differ between the two sources, so the duplicate is not detected
anyway. Worth knowing when a company appears twice in the ledger.

---

## 4. The title filter

The one place jobs are deliberately discarded. `is_relevant()` lowercases the title and
keeps it if any of the 19 terms in `title_filter_terms` appears as a substring.

Last run: **1,180 → 990**, dropping 190.

This is a cheap gate before an expensive one. Every job that survives costs roughly $0.013
to score, so dropping 190 non-PM roles saves about $2.40 per run — and, more importantly,
keeps the ledger scannable.

Two known behaviors of substring matching:

- Terms are padded where needed (`" pm "`, `"pm,"`, `"pm -"`) because a bare `"pm"` matches
  *shipment*, *employment* and *development*.
- It is a **title** filter only. A genuine AI PM role titled "Product Owner, ML Platform"
  passes; one titled "Technical Program Lead" does not, and is silently lost. The filter is
  tuned to accept some noise rather than lose signal, but it does lose some.

---

## 5. Writing to the ledger

`sheets.append_new_jobs()` reads column A, builds a set of existing ids, filters the batch,
and writes everything left in **one** `append_rows` call.

Two properties matter downstream:

- **Append-only.** Discovery never updates an existing row. A row you have edited, scored,
  or marked `applied` is untouchable by this stage — the second dedupe layer, and the reason
  re-running is always safe.
- **`status` is seeded to `new`,** and scoring columns are written as empty strings so the
  scorer's "has this been scored" check is a simple blank test.

---

## What discovery does *not* do

Deliberate omissions, each of which belongs to a later stage:

- **No scoring or ranking.** Relevance beyond the title filter is the scorer's job.
- **No company enrichment.** Size, funding and product lines are fetched later, by
  `contact_extract.py`, only for companies that actually matter.
- **No deletion.** Stale roles accumulate; `posted_at` lets later stages ignore them.
- **No description fetching.** If a source returns an empty description, it stays empty.

---

## Running it

```bash
python3 job_search.py
```

Roughly 3–5 minutes, dominated by the 39 sequential Greenhouse calls at 0.5s apart.

**Reading the output.** The per-source counts at the end are the health check. Compare
against the typical yields in the table above:

| Symptom | Likely cause |
|---|---|
| JSearch total near zero | `RAPIDAPI_KEY` expired or quota exhausted |
| One Greenhouse slug 404s | Company left Greenhouse — remove it from `target_companies.json` |
| Apify warning | Actor changed or timed out; expected occasionally, ignore unless persistent |
| Pre-filter drops almost everything | `title_filter_terms` was edited badly |
| "0 already in sheet" on a re-run | Pointing at a different sheet than you think |

### Automation

`.github/workflows/daily_job_search.yml` runs this stage daily at 13:00 UTC (5am PT) on
GitHub Actions, using Python 3.11 and repository secrets. Scoring is **not** in the workflow
— it is expensive and long, so it stays a deliberate local action.

---

## Configuration

| File | Controls | Committed |
|---|---|---|
| `config/search_config.json` | queries, title filter, freshness window | yes |
| `config/target_companies.json` | Greenhouse slugs | yes |
| `config/filters.py` | `detect_remote()` | yes |
| `.env` | `RAPIDAPI_KEY`, `APIFY_TOKEN` | **no** |

Tuning notes: adding queries is nearly free against quota; widening `date_posted_filter`
mostly returns roles you have already seen; loosening `title_filter_terms` raises scoring
cost linearly.

---

## Known weaknesses

Ordered by how much they cost you:

1. **VC portfolio jobs have no descriptions** — ~30 rows per run cannot be scored
   meaningfully. Either fetch each description separately, or drop the source.
2. **The title filter is title-only** — an AI PM role under an unusual title is lost
   silently, and nothing counts what was dropped.
3. **Ashby and Lever companies are listed but never fetched** — the config implies coverage
   that does not exist.
4. **URL-derived ids drift** — a re-posted job returns as a new row.
5. **Greenhouse is sequential** — 39 calls at 0.5s dominate the runtime, and the boards are
   independent, so this could be concurrent.
