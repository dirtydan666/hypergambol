"""
Scores candidates whose horizon has elapsed.

    python -m harness.score

Grades everything, not just the tradeable ones. A signal that fires on nothing
and a signal that fires on noise look identical until you score the misses too.
"""

from __future__ import annotations

import time

from . import config, store
from .signals import basis, perps

SIGNALS = {basis.SIGNAL: basis, perps.SIGNAL: perps}
HORIZONS = {
    basis.SIGNAL: config.BASIS_HORIZONS_HOURS,
    perps.SIGNAL: perps.HORIZONS_HOURS,
}

# Only grade candidates the board would have shown as meaningful.
GRADEABLE_STATUSES = {"tradeable", "not_fillable", "clean_no_trade", "fired"}


def main() -> int:
    now = int(time.time())
    already = store.scored_ids()
    outcomes: list[dict] = []

    for candidate in store.read(store.CANDIDATES):
        signal = candidate.get("signal")
        module = SIGNALS.get(signal)
        if module is None or candidate.get("status") not in GRADEABLE_STATUSES:
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
                })
                continue

            result = module.score(candidate, horizon)
            if result:
                outcomes.append(result)

    store.append_many(store.OUTCOMES, outcomes)

    graded = [o for o in outcomes if o.get("status") == "scored"]
    print(f"{len(outcomes)} outcomes written, {len(graded)} graded")
    for o in graded:
        print(
            f"  {o['ticker']:<5} {o['horizon_hours']:>3}h  "
            f"{o.get('ticker') or o.get('coin') or '-':<6} "
            f"{o.get('edge_bps', o.get('captured_bps', 0)):+5}bps  "
            f"{'right' if o.get('profitable') else 'wrong'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
