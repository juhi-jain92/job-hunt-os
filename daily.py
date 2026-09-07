"""
daily.py — The whole pipeline, one command, in order. Every stage is
independent: a failure is logged and the next stage still runs, and the run
ends with a one-screen summary of what landed and what didn't.

    file yesterday's sent marks → discover → prune (>7d) → score (capped)
             → referral match → networking queue → draft notes
             → follow-ups & stale → rebuild Today

Same command locally and in the 5:30am GitHub Actions run.

Usage:
    python3 daily.py                 everything
    python3 daily.py --no-spend      skip the two stages that cost money
    python3 daily.py --from draft    start at a stage: marks|discover|prune|score|match|network|draft|track|today

Stages live in stages/ and run as modules (python3 -m stages.match_scorer) so
that the repo root stays on the import path. Shared code is in lib/.
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))

SCORE_CAP = 100      # ~60 cents worst case; keeps a bad day from becoming a bad bill
DRAFTS_PER_DAY = 5   # per lane: 5 referral + 5 networking

STAGES = [
    ("marks",    ["-m", "stages.today", "--absorb-only"], False),
    ("discover", ["-m", "stages.job_search"],            False),
    ("prune",    ["-m", "stages.prune_ledger"],          False),
    ("score",    ["-m", "stages.match_scorer", "--limit", str(SCORE_CAP)], True),
    ("match",    ["-m", "stages.referral_match"],        False),
    ("network",  ["-m", "stages.networking_daily"],      False),
    ("draft",    ["-m", "stages.draft_notes", "--n", str(DRAFTS_PER_DAY)], True),
    ("track",    ["-m", "stages.outreach_tracker"],      False),
    ("today",    ["-m", "stages.today"],                 False),
]

NO_SPEND = "--no-spend" in sys.argv
start = STAGES[0][0]
if "--from" in sys.argv:
    try:
        start = sys.argv[sys.argv.index("--from") + 1]
    except IndexError:
        pass


def main():
    names = [s[0] for s in STAGES]
    if start not in names:
        sys.exit(f"unknown stage {start!r}; choose from {names}")
    results = []
    t0 = time.time()
    for name, cmd, spends in STAGES[names.index(start):]:
        if spends and NO_SPEND:
            results.append((name, "skipped (--no-spend)", 0))
            continue
        print(f"\n{'═' * 60}\n  {name.upper()}  ·  {' '.join(cmd)}\n{'═' * 60}")
        t = time.time()
        proc = subprocess.run([sys.executable, *cmd], cwd=ROOT)
        results.append((name, "ok" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})",
                        time.time() - t))

    print(f"\n{'═' * 60}\n  DAILY RUN SUMMARY  ·  {(time.time() - t0) / 60:.0f} min\n{'═' * 60}")
    for name, status, secs in results:
        print(f"  {name:<9} {status:<24} {secs:5.0f}s")
    failed = [n for n, s, _ in results if s.startswith("FAILED")]
    if failed:
        print(f"\n  Stages needing attention: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
