# Job Hunt OS — Architecture

Three stages, one sheet. Discovery fills the ledger, the scorer prices every row,
the referral lane turns 7+ rows into people to ask. Nothing sends anything, ever —
every message leaves from Juhi's own hands.

```
discovery ─▶ ledger (sheet1) ─▶ scorer ─▶ score >= 7 ─▶ referral match ─▶ Referrals tab ─▶ you send
                                                              ▲
                                          contacts_ingest ────┘  (two LinkedIn CSVs)
```

---

## 1 · Discovery — `job_search.py`

Fetch → normalize → dedupe → title-filter → append. No model calls. Idempotent:
re-running adds only unseen `job_id`s.

| Source | Auth | Typical yield | Notes |
|---|---|---|---|
| JSearch | `RAPIDAPI_KEY` | ~660 | 18 queries × 5 pages = 18 requests of a 10k/mo quota; `"week"` freshness server-side; timeouts retry once, other errors don't |
| Greenhouse | none | ~420 | 39 boards from `target_companies.json`, 8 concurrent |
| Wellfound | `APIFY_TOKEN` | ~50 | third-party actor, the slow stage (up to ~3 min) |
| VC portfolios | `APIFY_TOKEN` | ~30 | **no descriptions** — marked unscorable without a model call |

**The ledger — 11 columns:**

```
job_id | title | company | location | source | posted_at | score | status | notes | url | description
```

Discovery writes everything except `score` and `notes`, seeds `status = "new"`.
Appends are pinned to the header table (`table_range="A1"`) so stray blank rows can
never push data down or sideways again. Rows the user marks `applied` / `interviewing` /
`rejected` / `skipped` are never touched by any script.

Runs daily at 5am PT via GitHub Actions; a full local run is ~6–10 min, dominated by
JSearch pacing and the Wellfound actor.

---

## 2 · Scoring — `match_scorer.py`

One call per unscored row: **the resume key details vs. the JD.** Sonnet 5 at
`effort: low` — A/B-tested: medium effort doubled cost and changed zero 7+ decisions;
disabling thinking was slower *and* more expensive.

**Division of labor.** The model only judges; Python computes everything derivable.
The same A/B showed the model botching its own arithmetic ~1/3 of the time, so no
derived number is ever asked of it.

Model returns 6 fields:

```
domain 0-3 · ai 0-3 · skills 0-2 · level 0-2 · dealbreaker "" or reason · reason
```

Python derives:

- `score` = the sum (0–10) — the only number in the sheet
- skip = any dealbreaker, or score ≤ 6
- `status`: `low match` / `spray` / `ready to apply` (7+)
- `notes` = the reason, prefixed `DEALBREAKER:` when one fired

Dealbreakers the model watches for: salary top clearly under the floor, production
coding as a hard requirement, sales/account role, agency.

**Cost.** The static prefix (rubric + preferences + resume key details, ~4K tokens)
is prompt-cached at 0.1× from the second call on; only the job posting (~1K) bills
at full rate. Full pass over ~970 jobs: **~$5.80, ~90 min.** Batch-writes every 25
rows, resumes from the last unscored row after any interruption.

```bash
python3 match_scorer.py --estimate     # cost, no scoring
python3 match_scorer.py --preview 3    # model JSON + derived row, writes nothing
caffeinate -dims python3 match_scorer.py
```

The resume key details live in `KEY_DETAILS` inside the script, distilled from
`resume/Juhi_Jain_Resume.pdf` — refresh that block when the PDF changes.

---

## 3 · Referral lane

Two scripts on either side of the Contacts tab, both deterministic — no model calls,
so `--preview` output is exact.

### 3a · `contacts_ingest.py` — network → Contacts tab

Input: two LinkedIn exports at `data/connections/juhi_connections.csv` and
`anchit_connections.csv` (gitignored; LinkedIn → Settings → Data privacy → Get a
copy of your data → Connections).

- Finds the header row by scanning (LinkedIn's preamble length varies)
- Normalizes company names; `seniority_hint` derived from the title
  (`recruiter` / `exec` / `director+` / `manager` / `ic`)
- **Tie inference** from `config/past_employers.json` (extracted from the resume,
  ISB and DTU included): a connection made during a tenure window *and* 18+ months
  old ⇒ `dormant` — trust worth reviving; everything else ⇒ `first_degree`
- Same person in both files ⇒ `owner: both`; re-ingesting a fresh export updates
  company/title in place (people change jobs) and appends the new
- Hand-edited `tie_type` values are never overwritten

```bash
python3 contacts_ingest.py --dry-run --stats    # check the parse first
python3 contacts_ingest.py
python3 contacts_ingest.py --report-unmatched   # then spend 15 min on company_aliases.json
```

### 3b · `referral_match.py` — 7+ roles × contacts → Referrals tab

One row per qualifying role, because the daily question is per-role: *does this job
have a warm path, and through whom?*

**Company matching** (`normalize.py`) in four confidence stages: exact → alias
(`config/company_aliases.json`) → subset → fuzzy. The first three auto-fill slots;
**fuzzy never does** — a wrong company name on a warm-tie message is the most
embarrassing failure available, so fuzzy is skipped unless `--allow-fuzzy`, and even
then it's flagged in notes for a human to confirm.

**Contact ranking** — two slots against maybe eight contacts is a decision about
which ask to spend: first-degree beats dormant, product title beats non-product,
senior beats junior, recent connection beats old. Recruiters route to their own slot
so they never displace a referrer.

**Referrals tab (one row per role):**

```
job_id … posted_at | score | notes | first_degree_available |
referrer_1 (+owner) | referrer_2 (+owner) | recruiter |
note_to_send | fallback_contact | sent_1 | sent_2 | sent_rec | followup_due
```

Names are `=HYPERLINK()` cells — the name is the click target. No contact inside ⇒
`fallback_contact` gets a LinkedIn people-search link. Three separate sent-date
columns because you'll routinely message one person and not the other; existing rows
are never overwritten on re-run.

```bash
python3 referral_match.py --preview 5     # exact dry run
python3 referral_match.py                 # write the tab
python3 referral_match.py --fresh-only    # roles posted in the last 48h
```

### 3c · `outreach_tracker.py` — follow-ups and caps

Runs over both lanes. Referral side: `followup_due` = earliest send + 7 days (the
ask waiting longest). Networking side: flags 7-day-old unanswered sends, clears
flags on reply, holds queued connection requests over the 15/week cap, and reports
anything marked sent without the personalization box ticked. Rows in a user-owned
status are never rewritten.

---

## Guardrails (non-negotiable)

- **Human sends everything.** Scripts fill a draft queue; nothing transmits on any channel.
- **No automation against LinkedIn.** URL generation only; the CSVs come from
  LinkedIn's own export.
- **15 connection requests/week**, enforced by the tracker as HELD rows. DMs to
  existing connections and cold email are uncapped — which is why they're the
  primary routes.
- **Fuzzy matches never auto-fill.** Machine narrows, human decides.

## What's not built yet

| Piece | Blocks | Blocked on |
|---|---|---|
| `draft_generator.py` | `note_to_send` stays empty — messages written by hand for now | resume + story bank are in; build is next |
| Networking lane people-finding | cold-email prospects come as search links, not names | `HUNTER_API_KEY` in `.env` ($34/mo Starter) |
| Ashby/Lever fetchers | ~11 listed companies never fetched | a small fetcher each |
