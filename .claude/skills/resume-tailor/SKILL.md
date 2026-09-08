---
name: resume-tailor
description: Pick which of Juhi's two resume versions to send, decide whether a role needs any edit at all, handle ATS keyword gaps, and validate a version tailored elsewhere (TrueUp, Teal, an LLM). Use when she pastes a JD and asks which version, whether to tailor, or asks to check a tailored resume before sending.
---

# Resume Tailor

She has two documents and keeps two documents. Tailoring is reordering inside
one of them, never a rewrite, and the default answer is "no edits, send it."
She has said plainly she cannot spend hours per application. Protect that.

**Version A, AI-native.** Title leads "AI-native Product Leader"; Core Skills
lead Applied AI; the LG Ads AD block leads AI Portfolio Strategy.

**Version B, AdTech.** Title leads "Programmatic & CTV Product Leader"; Core
Skills lead Ad Tech Domain; the AD block leads Identity Infrastructure, then
Product Vision, then GDPR.

## Step 1: which version

Read the JD's **required qualifications** block, not the blurb. Whichever comes
first wins:

- Advertising, measurement, attribution, identity, marketplace, retail media,
  supply or demand, trust and safety, ads policy: **Version B**
- AI, agents, LLMs, evals, ML platform, applied AI: **Version A**
- Genuinely both, or neither: **Version B**. It reads as a domain operator who
  also ships AI, which is the truer and rarer story.

## Step 2: does it need any edit

Almost always no. Say so in one line and move on.

Only two things justify an edit, and each is capped:

**a) The lead bullet is buried.** If one bullet in the LG Ads AD block is
obviously *the* job (Evals/Guardrails/HITL for an ads-review role, Identity for
an identity role, GDPR for a privacy role), move it to position one. One cut
and paste.

**b) A hard-required literal term never appears in the document.** See ATS below.
One line added to a Core Skills row.

**Hard cap: three changed lines per role.** If a JD seems to need more than
three, the answer is not more tailoring, it is that the role is a weak fit or
the wrong version was picked. Say that instead.

## ATS: what actually matters

Most of what is said about ATS optimization is false and expensive. What is
true:

- **Greenhouse, Ashby, Lever do not auto-reject on a keyword score.** They store
  the resume and let a recruiter search it. Keywords matter for whether she
  surfaces in that search, not for a robot rejection.
- **Workday, iCIMS and Taleo parse harder and gate on knockout questions.**
  Chewy, most large retailers, and most enterprises are Workday. The knockout
  questions (years of experience, work authorization, location, salary) decide
  more than the resume parse does. Answer those carefully; do not rewrite the
  resume to beat a parser.
- **The only ATS edit worth making is the literal-term fix.** If the JD names a
  hard requirement in words her resume never uses ("retail media", "sponsored
  products", "incrementality", "media mix modeling", "ads policy enforcement"),
  and she genuinely has the experience under a different name, add that exact
  term to the matching Core Skills row. One line. Never invent the experience
  to justify the term.
- **Her document already parses cleanly.** Single column, standard section
  headings, no tables, no text boxes, no headers or footers, real text not
  images. Nothing about format needs changing, ever. Do not suggest stripping
  formatting, removing bullets, or a "plain text ATS version."

## Never touch

Metrics, dates, titles, company names, employer names, the honest limits. A
requirement she does not meet is handled in outreach and interviews, not by
editing the resume.

## Producing the edits

She edits her own Google Doc and exports. Never generate a replacement PDF or
docx unless she asks: a near-miss on her layout looks worse than no tailoring.

Give each change as a copy-paste block: the exact current text, then the exact
replacement. Reorderings are stated as cut and paste with the new order listed,
never as retyped text. No prose explanation above three lines.

## Validating a version tailored elsewhere

Auto-tailoring tools mirror the JD's language back into the summary, where no
bullet can contradict it. That is where their failures live, so read the summary
line by line against the bullets before anything else.

Check against the honest limits in `stages/match_scorer.py` (KEY_DETAILS) and
the story bank:

| Check | Fails if the document says |
|---|---|
| Coding | wrote, built, or shipped production code; "software engineer" |
| Model work | fine-tuned, trained a model, built a RAG pipeline, vector DB at scale |
| Seniority | Director, VP, Head of, or anything above Associate Director |
| Multi-agent | multi-agent claims attached to LG Ads work (Vectorial only) |
| Portfolio projects | Job Hunt OS / ThinkOS / ContractIQ described as shipped commercial products, with users or revenue |
| Diagnostic agent | called a "chatbot" or "RAG chatbot" rather than deterministic retrieval with LLM intent routing |
| Scope redefinition | the $400M business described as something other than demand, supply, identity and monetisation |
| Counts | a count of systems or workflows recharacterized so all of them match the JD (three workflows are ad review, multimodal generation, diagnostics; only one is risk-routing HITL) |
| Metrics | any number not traceable to the story bank or resume verbatim |
| Self-adjectives | "known for", "proven", "passionate", "results-driven" |
| Em dashes | any em dash or en dash in prose |

Report line by line: quote the offending text, name the flag, give the honest
replacement. Lead with the two or three that actually matter; do not hand her a
report longer than the resume.
