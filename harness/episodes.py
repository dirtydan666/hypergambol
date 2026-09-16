"""
Episode de-duplication — fix #1, and the one that poisons every number above it.

A capture runs every 15 minutes. A crowded-funding condition can persist for
days. Logging it every capture is correct — that is the observation history, and
it is what makes offline re-grading possible. But *grading* it every capture is
not: it turns one situation into ~96 "calls" a day and lets the longest-lasting
conditions dominate every average purely because they lasted.

The first three days of real data: 5,323 graded outcomes from **61 distinct
subjects**. NVDA alone was 518 of them. AVAX 331. That is not a sample of 5,323,
it is a sample of 61 measured over and over.

So a candidate is graded only when it STARTS an episode — when what the harness
says about that subject differs from what it said last capture. Everything else
stays logged and readable.

Deliberately computed from the candidate log rather than at detection time, so
it applies retroactively to data already collected.
"""

from __future__ import annotations

# If nothing was recorded about a subject for this long, whatever comes next is
# a fresh episode rather than a continuation - the condition lapsed in between.
EPISODE_GAP_SECONDS = 2 * 3600

# Statuses that represent a claim about the future and can therefore be graded.
CLAIMABLE = {"tradeable", "fired", "not_fillable", "clean_no_trade"}

# Which claim each status makes. "act" and "abstain" are different assertions
# and must never share a hit rate: one says the trade pays, the other says
# staying out is right. Mixing them is fix #2.
CLAIM_OF = {
    "tradeable": "act",
    "fired": "act",
    "not_fillable": "abstain",
    "clean_no_trade": "abstain",
}


def subject_of(record: dict) -> str:
    """Signals name their subject differently. One key for all of them."""
    who = record.get("ticker") or record.get("coin") or record.get("venue") or "?"
    return f"{record.get('signal', '?')}:{who}"


def signature_of(record: dict) -> str:
    """
    What has to change for this to count as a new call rather than the same one
    still being true. Status alone is too coarse: a coin flipping from crowded
    short to crowded long is a new claim, not a continuation.
    """
    return f"{record.get('status', '?')}|{record.get('kind', '')}"


def annotate(records: list[dict]) -> list[dict]:
    """
    Returns the same records, each with `episode_start` and `claim` set.
    Input need not be sorted; output is ordered by time.
    """
    ordered = sorted(records, key=lambda r: r.get("detected_at") or 0)
    last: dict[str, tuple[str, int]] = {}

    for record in ordered:
        status = record.get("status")
        record["claim"] = CLAIM_OF.get(status)

        if status not in CLAIMABLE:
            record["episode_start"] = False
            continue

        subject = subject_of(record)
        signature = signature_of(record)
        now = record.get("detected_at") or 0

        previous = last.get(subject)
        if previous is None:
            start = True
        else:
            prev_sig, prev_ts = previous
            start = (signature != prev_sig) or (now - prev_ts > EPISODE_GAP_SECONDS)

        record["episode_start"] = start
        last[subject] = (signature, now)

    return ordered


def episode_starts(records: list[dict]) -> list[dict]:
    return [r for r in annotate(records) if r.get("episode_start")]


def summarise(records: list[dict]) -> dict:
    """How much of the log was repetition. Worth printing every run."""
    annotated = annotate(records)
    claimable = [r for r in annotated if r.get("status") in CLAIMABLE]
    starts = [r for r in claimable if r["episode_start"]]
    subjects = {subject_of(r) for r in claimable}
    return {
        "claimable_records": len(claimable),
        "episodes": len(starts),
        "distinct_subjects": len(subjects),
        "repetition_factor": round(len(claimable) / len(starts), 1) if starts else None,
    }
