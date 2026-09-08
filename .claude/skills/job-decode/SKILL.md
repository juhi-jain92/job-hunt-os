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

## 3. Find who to contact, in this order

Work the ladder and stop at the first rung that produces a name. Never invent
an address; never hand her a search link when a verified address was reachable.

**Rung 1, first degree.** Her own connections export.

```bash
grep -i -h "<company>" data/connections/*.csv | head -20
```

A hit here outranks everything below it. That is a referral ask, not a cold email.

**Rung 2, Hunter domain search.**

```python
from lib.contact_extract import hunter_domain_search
r = hunter_domain_search(domain="acme.com")   # merges the department slices
```

**Hunter has no "product" department.** The taxonomy is executive, it, finance,
management, sales, legal, support, hr, marketing, communication, design,
operations. Product people land under management, executive, or occasionally
it. Searching for "product management" returns nothing; do not keep trying
variants. The merged slices already cover it.

**Rung 3, derive the pattern and verify.** When Hunter returns only comms, HR
and support (normal at any large retailer or enterprise), read the pattern off
the addresses it did return, find the person's name on LinkedIn or in press,
construct the address, and verify it before handing it over:

```bash
curl -s "https://api.hunter.io/v2/email-verifier?email=X&api_key=$HUNTER_API_KEY"
```

Hand over only `status: valid` with `smtp_check: true` and `accept_all: false`.
Record a confirmed pattern in `config/company_meta.json` as `email_pattern`
(`{f}{last}` for jsmith@, `{first}.{last}` for john.smith@) so the next role at
that company costs nothing.

**Rung 4, LinkedIn second degree**, for people whose name she must find herself:
`https://www.linkedin.com/search/results/people/?keywords=<company>%20<team>&network=%5B%22S%22%5D`
Second degree, so mutual connections are visible and an intro path exists.

**Press is a contact source, not just a hook.** One search on the company's ads
or product leadership routinely names the person Hunter cannot, and their
background is usually the sharpest thing to open on.

## 4. Which resume version

Defer to `.claude/skills/resume-tailor/SKILL.md`. Answer in one line: Version A
or Version B, and either "no edits" or at most three changed lines. Never more.

## 5. Write the outreach, always

**This step is not optional and is never replaced by advice about who to
contact.** Every role decoded ends with drafts she can paste and send tonight.
Produce all of:

- **A cold email** to the best contact: subject under 60 characters, at most 4
  bullets, under 150 words, one verbatim story-bank metric, closing ask.
- **A LinkedIn note** to the same person, under 300 characters, no bullets, no
  greeting block, no signature.
- **A second LinkedIn note** for the hiring manager or team lead she must find
  herself, with the search link and a `[name]` placeholder.
- **A backup contact** with a one-line rule for when to use it (usually: no
  reply in ten days, same email, different subject).

Where a first-degree connection exists, the first draft is a referral ask
instead of a cold email, and it asks for the referral explicitly.

Follow `.claude/skills/networking-note/SKILL.md` for the format. No em dashes
anywhere. Rotate stories across a batch; never spend one story on two companies
in the same reply.

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
