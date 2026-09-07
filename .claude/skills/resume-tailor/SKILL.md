---
name: resume-tailor
description: Tailor Juhi's resume for a specific role, or validate a version she tailored elsewhere (TrueUp, Teal, an LLM). Use when she asks how to personalise her resume, whether to tailor for a role, or asks to check a tailored version before sending.
---

# Resume Tailor

One master document, small reorderings, never a rewrite. She edits her own
Google Doc and exports the PDF, so the formatting stays hers. Never generate a
replacement PDF or docx unless she explicitly asks: a near-miss on her layout
looks worse than no tailoring.

## First: does this role even need it?

Default is **no**. Tailor only when the role hires for the adtech decade rather
than the AI work. Test: does the JD's required-qualifications block name
advertising, measurement, marketplace, identity, or trust and safety before it
names AI? If yes, tailor. If the role leads with AI, agents, or evals, send it
as is; the resume already leads there.

## The five levers, in order of effect

Her resume structure: title line, summary paragraph, CORE SKILLS (four rows),
PROFESSIONAL EXPERIENCE (Vectorial, LG Ads AD, LG Ads Senior PM, Alphonso, EXL),
AI PROJECTS, EDUCATION.

1. **Title line.** Default is "AI-native Product Leader | 0-to-1 Products |
   Programmatic Advertising, CTV & Applied AI". For an adtech-first role, lead
   with the domain instead of AI-native. Reordering only, no new claims.
2. **CORE SKILLS row order.** Default is Applied AI, Product Leadership, Ad Tech
   Domain, Technical Fluency. For adtech-first roles move Ad Tech Domain to row
   one. This is the single highest-leverage edit: it is what a keyword screen and
   a six-second human scan both hit.
3. **Bullet order inside the LG Ads AD role.** Six bullets exist: AI Portfolio
   Strategy, Evals/Guardrails/HITL, AI Architecture Judgment, Product Vision,
   Identity Infrastructure, GDPR. Promote the two or three that match the JD's
   own words. Do not delete the others.
4. **Summary paragraph, first clause only.** Swap which half leads. The metrics
   stay identical.
5. **AI PROJECTS section.** Keep it for AI roles. For a pure adtech role it can
   move below Education, never deleted.

## Never touch

Metrics, dates, titles, company names, the honest-limits reality. If a JD asks
for something she does not have, the answer is the gap script in her outreach,
not a resume edit.

## Validating a version tailored elsewhere

Run this checklist against the accuracy flags in the `juhi-job-strategy` skill's
`references/profile.md`. Auto-tailoring tools violate these routinely because
they mirror the JD's language back.

| Check | Fails if the document says |
|---|---|
| Coding | wrote, built, or shipped production code; "software engineer" |
| Model work | fine-tuned, trained a model, built a RAG pipeline, vector DB at scale |
| Seniority | Director, VP, Head of, or anything above Associate Director |
| Multi-agent | multi-agent claims attached to LG Ads work (Vectorial only) |
| Portfolio projects | Job Hunt OS / ThinkOS / ContractIQ described as shipped commercial products, with users or revenue |
| Diagnostic agent | called a "chatbot" or "RAG chatbot" rather than deterministic retrieval with LLM intent routing |
| Metrics | any number not traceable to the story bank or resume verbatim |
| Em dashes | any em dash or en dash anywhere |

Report line by line: quote the offending text, name which flag it breaks, give
the honest replacement. Approve only when every check passes.

## Output shape

For a tailoring request: name the role, say tailor or send as is, then list the
specific edits as "move X above Y" with the exact current text. Under ten lines.
She should be able to make every edit in two minutes without reading prose.
