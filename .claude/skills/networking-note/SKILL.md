---
name: networking-note
description: Draft a personalized outreach note for one networking prospect or referral ask in Juhi's Job Hunt OS. Use whenever Juhi asks to write, draft, or fill a note_to_send / draft_body for a company or person in the Referrals or Networking tab, or says "write the note for X". Produces brief bullets, never sends anything.
---

# Networking Note

Write one outreach note for one target. The note is bullets, not prose — Juhi
personalizes the last 10% and sends it herself. Nothing is ever sent by you.

## Research steps, in order (all free — no API spend)

1. **Their product** — company site / docs. What do they actually sell, to whom,
   and what is the hard problem underneath (auction? attribution? supply-demand?
   ops workflow?).
2. **Recent news** — one WebSearch: funding, launches, partnerships, controversy.
   The freshest specific fact wins; a note that could have been written last year
   convinces no one.
3. **Problems they face** — read between the lines: skeptical press, competitor
   pressure, an integration push, a pivot. This is where the hook lives.
4. **Her story match** — read `resume/story-bank.md` (13 enriched stories, STAR
   format). Pick the ONE story whose "Earned secret" line speaks to their problem.
   Check the story's `Use Count` / `Last Used` — do not spend the same story on
   two companies in the same week; rotate.
5. **Her experience frame** — `match_scorer.py` KEY_DETAILS block has the
   distilled resume. Metrics must come from there or the story bank verbatim —
   never invent or round up.

## Output format (brief bullets, in this order)

```
• [Their product, one line — proves she understands what they build]
• [Fresh specific observation: news/problem — the personalization hook]
• [Her matching story in one line, with ONE metric — how it solves their problem]
• [The ask: excited to be considered for a product role / a 15-min conversation]
```

4 bullets, ≤ 280 words total. LinkedIn connection notes: ≤ 280 CHARACTERS.

## Guardrails (from the PRD, non-negotiable)

- DRAFT only. Write into `note_to_send` (Referrals) or `draft_body` (Networking);
  status stays DRAFT/PROSPECT. Never mark sent, never send.
- Every note must contain one target-specific observation (the hook). No hook →
  don't write the note; flag it instead.
- Honest limits: no production coding, no fine-tuning/RAG hands-on claims,
  nothing above Associate Director. Portfolio projects are portfolio projects.
- Blocked companies (config/target_companies.json → blocked_companies): refuse.

## When she says "note sent"

Update the row: sent date column (`sent_1`/`sent_2`/`sent_rec` on Referrals,
`sent_date` + status SENT on Networking) with today's date, and bump the story's
`Use Count` / `Last Used` in resume/story-bank.md.
