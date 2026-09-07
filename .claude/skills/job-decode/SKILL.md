---
name: job-decode
description: Decode a job description Juhi pastes in: score it with the real pipeline rubric, explain whether the pipeline saw it and why not, find who to contact, call the tailoring question, and write the outreach. Use whenever she pastes a JD or a batch of them, or asks "is this worth applying to", "who do I reach out to", "should I tailor my resume for this".
---

# Job Decode

A pasted JD gets the same treatment every time. Never eyeball a score, never
guess an email, never skip the honest gap.

## 1. Score it with the real rubric, not judgment

Build the job dict and call the pipeline scorer so the number matches what the
sheet would produce. Preserve the JD's hard requirements verbatim in the
description, especially degree, years, domain, coding and location lines, or
the score will be wrong in her favour.

```python
import sys; sys.argv=["x"]
sys.path.insert(0,"/Users/juhi/Juhi AI Projects/job-hunt-os")
from stages import match_scorer as ms
r = ms.score_job({"title":..., "company":..., "location":..., "description":...})
d = ms.derive(r, "new")   # score, status, notes
```

Report `score/10`, the four dimensions (`domain ai skills level`), and any
dealbreaker. Batch several JDs in one script; it is one API call each.

**When the rubric is wrong, say so and explain why.** It scores domain against
adtech and AI. It under-credits marketplace, ranking, auction, trust-and-safety
and measurement roles that are structurally her work in another vertical. Give
the rubric number first, then the revised read with the evidence.

## 2. Check whether the pipeline already had it

```python
from lib import sheets
jobs = sheets.get_all_rows_with_numbers(sheets._spreadsheet().worksheet("Jobs"))
[r for r in jobs if "acme" in (r.get("company","") or "").lower()]
```

Then explain the miss honestly. The usual causes, in order:

| Cause | How to tell |
|---|---|
| It did show up, she has not looked | Row exists in Jobs with a score |
| Company's ATS is not watched | Not in `greenhouse_slugs` / `ashby_slugs` / `lever_slugs` |
| ATS type has no fetcher | Workday, Google's own careers, SmartRecruiters, iCIMS |
| Behind a login | a16z speedrun, Lenny's, any talent network |
| Older than the 7-day window | `posted_at` older than the prune cutoff |
| Title filter dropped it | Title lacks any `title_filter_terms` string |

If the company has a watchable board, offer to add it to
`config/target_companies.json` plus its domain in `config/company_meta.json`.

## 3. Find who to contact

```python
from lib.contact_extract import hunter_domain_search
r = hunter_domain_search(domain="acme.com")   # already merges department slices
```

Rank product leadership first: Head of Product, VP Product, CPO, Director of
Product, Principal, Staff, GPM. Founders and CTO at companies under ~100 people.
If Hunter returns only sales and ops, say so and fall back to a LinkedIn
people-search link. Never invent an address. Flag confidence under 85%.

At a large company (Google, Reddit, Amazon) Hunter is close to useless and the
right route is a LinkedIn search for the specific org, or her own network.

## 4. Call the tailoring question

Default answer is **no**. She has one resume and it leads with AI. Tailor only
when the role's domain is her adtech decade rather than her AI work, and then
the change is a reordering, not a rewrite: move the $400M programmatic and
identity and monetization lines above the Vectorial block. Say explicitly which
lines move. Never suggest inventing or restating a metric.

## 5. Write the outreach

Follow `.claude/skills/networking-note/SKILL.md` exactly: 4 bullets maximum,
under 150 words, no em dashes ever, one verbatim metric from the story bank,
LinkedIn notes under 300 characters. Rotate stories across a batch; do not
spend the same story on two companies in one reply.

## Output shape

Per role, in one block: **score, the call (apply / apply with a caveat /
skip), the one-line reason, who to contact with the email or search route,
and the note.** Order a batch best-first. Group the skips at the end with one
line each. Never bury a 9 under a paragraph about a 6.

## Guardrails

Accuracy flags hold: no production coding, no fine-tuning, no RAG hands-on, no
seniority above Associate Director, portfolio projects are portfolio projects.
Blocked companies (`config/target_companies.json`) never surface. Watch for
PERM postings (job code, "multiple openings", legal entity D/B/A name, a
Master's plus exactly two years) and tell her not to spend a referral on one.
