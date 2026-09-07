# Job Hunt OS — Architecture

One pipeline, one schedule, one command, drafted rows out. Everything
below exists to make the **Today** tab true every morning. Nothing sends.

```
python3 daily.py            (12:30 UTC = 5:30am PDT / 4:30am PST, GitHub Actions — or by hand)

 discover ─▶ prune ─▶ score ─▶ match ─▶ network ─▶ draft ─▶ track ─▶ today
 Sheet1     Sheet1   Sheet1    Referrals Networking  both     both     Today
 free       free     ≤100/run  free      Hunter      ≤5/lane  free     ≤5/lane
```

Each stage is a standalone script with its own `--preview`/`--dry-run`; `daily.py`
runs them in order, logs failures, keeps going, and ends with a one-screen summary.
`--no-spend` skips the two stages that cost money.

## Definition of working

Five sends a day, from Juhi's hands, in a 20-minute block. Discovery and scoring
are inputs. The Today tab is the only surface she opens; if it is empty, the
pipeline failed, whatever the other tabs say.

## The tabs

| Tab | One row per | Written by | Juhi touches |
|---|---|---|---|
| **Today** | send-ready row (max 5 per lane) | today.py, regenerated each run | reads only |
| Sheet1 | job | discover, score | `status` if she applies |
| Contacts | person in either network | contacts_ingest (manual, on new export) | `tie_type` fixes |
| Referrals | role scoring 7+ | match, draft, track | `sent_1/2/rec` |
| Networking | cold prospect | network, draft, track | `status`, `sent_date`, `personalized` |

## Stages

**discover** — `job_search.py`. JSearch (18 queries), Greenhouse (38 boards,
concurrent), Wellfound, VC portfolios → one schema → dedupe by `job_id` → title
filter → append to Sheet1 anchored to the header table. Blocked companies dropped.
Zero rows from every source is a failure (non-zero exit), not a quiet day.

**prune** — `prune_ledger.py`. Deletes ledger rows posted more than 7 days ago;
rows with a status Juhi set (applied / interviewing / rejected / skipped) are
kept regardless. The full pre-prune ledger is parked in a hidden `ledger_backup`
tab before the rebuild, so a failed write cannot lose the ledger.

**score** — `match_scorer.py --limit 100`. Sonnet 5 at effort low judges four
dimensions + dealbreakers against the resume key details; Python sums the single
0–10 `score`. Prompt-cached; ~0.6¢/job; the cap keeps a bad day from becoming a
bad bill. Runs without the personal context store (defaults) so it works in CI.

**match** — `referral_match.py`. Sheet1 rows with `score ≥ 7` × Contacts →
Referrals, one row per role: two ranked referrer slots + recruiter (clickable
names), title-filtered search link when nobody is inside. Fuzzy never auto-fills.
Re-runs add only new roles.

**network** — `networking_daily.py`. 5 company/team slots a day: manual targets
first (config `manual_targets`, no board needed), then board-signal picks.
Cooldown is real now — a company with prospect rows generated in the last 14
days is skipped, so the same five no longer re-queue daily. Small company → 1–2
product leaders only; big → ≥5 across product orgs. Hunter names ranked by
title; uncertain emails verified, invalid ones dropped before the sheet.

**draft** — `draft_notes.py --n 5`. Picks up to 5 undrafted rows per lane (warm
referrals by score, then named prospects). For each: 2–3 web searches for a fresh hook,
one story from the committed `config/story_digest.json` (rotation: never a
story used in the last 7 days, tracked via `story_id`/`drafted_on` columns),
3–4 bullets. Python validates before writing: hook present, 3–4 bullets, a
verbatim metric from the story's impact line, ≤280 words (≤280 chars for
connection requests). Invalid → one retry → left blank for a human. Writes
`note_to_send` / `draft_body` + `personalization_hook`. ~6¢ a draft.

**track** — `outreach_tracker.py`. `followup_due` = earliest send + 7d;
unanswered flagged, answered cleared; weekly connect count reported (15 target);
sends without the personalization tick reported; **referrals posted 14+ days
ago and never chased are marked `stale`** and vanish from view (never deleted).

**today** — `today.py`. Rebuilds the Today tab: drafted, not stale, not sent,
max 5 per lane, warm referrals first. Prints the same to the terminal.

## Costs

Up to ~$1.20/day at the caps (100 scored roles at ~0.6¢ + 10 drafts at ~6¢ with
web search); a typical day is well under that. Hunter is on a paid plan; the
per-run caps (3 cold leads in match, 5 slots in network) keep its spend deliberate.

## Guardrails

Human sends everything · no automation against LinkedIn (URL generation and
LinkedIn's own export only) · connection requests counted weekly against a 15 target (reported, not enforced) · fuzzy matches never
auto-fill · every draft needs a target-specific hook · story rotation · blocked
companies (`config/target_companies.json → blocked_companies`) surface nowhere ·
scored rows and sent rows are never overwritten.

## Manual, occasional

- New LinkedIn export → `python3 contacts_ingest.py` (updates people in place).
- Resume changed → refresh `KEY_DETAILS` in `match_scorer.py`.
- Story bank changed → `python3 draft_notes.py --refresh-digest` (local only; the bank is gitignored) and commit `config/story_digest.json`.
- New target company → add to `manual_targets` (+ its domain in `company_meta.json` so Hunter fires).

## Known gaps (none block a send)

1. Cross-source duplicate roles (same job, two ids) — skip the twin.
2. Ashby/Lever companies in `target_companies.json` are never fetched.
3. VC-portfolio jobs carry no descriptions → marked, unscoreable.
4. Alias curation (`contacts_ingest.py --report-unmatched`) would surface a few more warm matches.
5. `Sheet2` in the spreadsheet is unidentified content — left untouched.
6. Contacts refresh is manual (`contacts_ingest.py` on a new LinkedIn export). If
   the Contacts tab is empty the referral lane exits 0 with nothing to do.
7. Cloud runs score without `config/context_store.json`; the scorer prints a
   warning and uses narrower location defaults than the local file.
8. The networking pool is ~57 companies against 5 slots × 14-day cooldown (70
   slot-days), so late in a cooldown window the lane will find nothing eligible.
   Adding `manual_targets` (with a `company_meta` domain) is the lever.
