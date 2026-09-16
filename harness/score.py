"""
Scores candidates whose horizon has elapsed.

    python -m harness.score

Grades everything the board would have shown as meaningful, not just the
tradeable ones. A signal that fires on nothing and a signal that fires on noise
look identical until you score the misses too.

Grades each SITUATION once, not each capture of it. See harness/episodes.py:
the first scorecard had 5,323 outcomes from 61 distinct subjects, because a
condition that stayed true for three days was counted as a fresh correct call
every fifteen minutes.
"""

from __future__ import annotations

import time

from . import config, episodes, store
from .signals import basis, meta, perps

SIGNALS = {basis.SIGNAL: basis, perps.SIGNAL: perps, meta.SIGNAL: meta}
HORIZONS = {
    basis.SIGNAL: config.BASIS_HORIZONS_HOURS,
    perps.SIGNAL: perps.HORIZONS_HOURS,
    meta.SIGNAL: meta.HORIZONS_HOURS,
}


def main() -> int:
    now = int(time.time())
    already = store.scored_ids()
    outcomes: list[dict] = []

    # Read the whole log, not a stream: whether a record starts an episode
    # depends on what came before it. Nothing here depends on what comes AFTER,
    # so a candidate's episode status never changes as new captures arrive.
    records = list(store.read(store.CANDIDATES))
    annotated = episodes.annotate(records)

    summary = episodes.summarise(records)
    print(f"{summary['claimable_records']} claimable records -> "
          f"{summary['episodes']} episodes across "
          f"{summary['distinct_subjects']} subjects "
          f"(repetition {summary['repetition_factor']}x)")

    for candidate in annotated:
        if not candidate.get("episode_start"):
            continue
        signal = candidate.get("signal")
        module = SIGNALS.get(signal)
        if module is None:
            continue

        for horizon in HORIZONS.get(signal, []):
            key = f"{candidate['candidate_id']}@{horizon}"
            if key in already:
                continue
            due_at = candidate["detected_at"] + horizon * 3600
            if now < due_at:
                continue
            # Don't grade something we only just became late for scoring on;
            # a stale grade is worse than none.
            if now - due_at > 3600 * 6:
                outcomes.append({
                    "candidate_id": candidate["candidate_id"],
                    "signal": signal,
                    "horizon_hours": horizon,
                    "scored_at": now,
                    "status": "missed_window",
                    "claim": candidate.get("claim"),
                })
                continue

            result = module.score(candidate, horizon)
            if result:
                # Stamp the claim type onto the outcome. "The trade pays" and
                # "staying out is right" are different assertions and must
                # never share a hit rate.
                result.setdefault("claim", candidate.get("claim"))
                outcomes.append(result)

    store.append_many(store.OUTCOMES, outcomes)

    graded = [o for o in outcomes if o.get("status") == "scored"]
    print(f"{len(outcomes)} outcomes written, {len(graded)} graded")
    for o in graded:
        # Signals name their subject differently. Assuming "ticker" here crashed
        # the whole step the moment a perps outcome was graded - and because the
        # outcomes are written before this print, the crash failed the job AFTER
        # the work was done, so nothing got committed and every grade was lost.
        who = o.get("ticker") or o.get("coin") or o.get("venue") or "-"
        # meta reports excess growth, not basis points. Printing them in one
        # column is how "+392bps" of market share ended up on a P&L scorecard.
        if o.get("excess_growth") is not None:
            measure = f"{o['excess_growth']:>5.2f}x mkt"
        else:
            measure = f"{o.get('edge_bps', o.get('captured_bps', 0)):+5}bps"
        print(
            f"  {o.get('signal', '?'):<6} {o.get('claim', '-'):<7} {who:<8} "
            f"{o['horizon_hours']:>3}h  {measure}  "
            f"{o.get('verdict') or ('right' if o.get('profitable') else 'wrong')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
