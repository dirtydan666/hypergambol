"""
Renders the scorecard - the thing that makes this credible rather than loud.

    python -m harness.report

Writes data/board.json (for the site) and prints a markdown scorecard for the
repo README. Reports rejection counts as prominently as hit rates, because
"we threw out four prints that looked like money" is the claim nobody else in
this category can make.

Three corrections the first scorecard needed, all applied HERE rather than by
rewriting history:

  1. One situation, one call. Outcomes are joined back to their candidate and
     kept only if that candidate started an episode. 5,323 outcomes from 61
     subjects becomes an honest count.
  2. Acting and abstaining are graded as different questions. A no-trade call
     is right when the trade would NOT have paid, so its verdict is the
     inversion of the trade's.
  3. meta is re-graded from its own stored shares against the market benchmark,
     and its measure is kept out of the basis-points column, where it was
     masquerading as money.

The append-only log is never edited. The raw records keep saying exactly what
they said; the reading of them is what got fixed.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from . import config, episodes, store
from .signals import meta as meta_signal

# What each signal's headline number actually measures. Mixing these in one
# column is how "+392bps" of market share ended up on a profit-and-loss board.
MEASURE = {
    "basis": ("net_after_costs_bps", "bps net of costs"),
    "perps": ("edge_bps", "bps in the called direction"),
    "meta":  ("excess_growth", "x growth vs the launchpad market"),
}


def _regrade(outcome: dict, claim: str | None) -> dict | None:
    """
    Recompute a verdict from fields already stored on the outcome.

    Nothing is refetched. Everything needed to answer the question correctly
    was recorded at the time; only the question was wrong.
    """
    if outcome.get("status") != "scored":
        return None

    signal = outcome.get("signal")
    row = {
        "signal": signal,
        "horizon_hours": outcome.get("horizon_hours"),
        "claim": claim or outcome.get("claim"),
        "subject": outcome.get("ticker") or outcome.get("coin")
                   or outcome.get("venue") or "?",
    }

    if signal == "meta":
        verdict, excess = meta_signal.assess(
            outcome.get("kind"),
            outcome.get("entry_share_pct"),
            outcome.get("exit_share_pct"),
        )
        if verdict is None:
            return None
        row["verdict"] = verdict
        row["measure"] = excess
        return row

    profitable = outcome.get("profitable")
    if profitable is None:
        return None

    if row["claim"] == "abstain":
        # The signal said stay out. It was right when the trade would have lost
        # money. Same evidence, opposite question - and the question the first
        # scorecard asked made a 97.6% record read as 2.4%.
        row["verdict"] = "wrong" if profitable else "right"
        row["abstain_cost_bps"] = outcome.get("net_after_costs_bps")
    else:
        row["verdict"] = "right" if profitable else "wrong"

    key, _ = MEASURE.get(signal, ("edge_bps", ""))
    row["measure"] = outcome.get(key)
    row["converged"] = outcome.get("converged")
    return row


def build() -> dict:
    candidates = list(store.read(store.CANDIDATES))
    annotated = episodes.annotate(candidates)

    # .get, not [], on every record in the log. Twice now a direct index on a
    # key one signal happened not to write has failed the job AFTER the work was
    # done - which loses the whole run, silently. A record with no id simply
    # cannot be joined to an outcome, so skipping it is also the right answer.
    episode_ids = {c["candidate_id"] for c in annotated
                   if c.get("episode_start") and c.get("candidate_id")}
    claim_of = {c["candidate_id"]: c.get("claim") for c in annotated
                if c.get("candidate_id")}

    by_status = Counter(c.get("status") for c in candidates)
    rejects_by_check = Counter()
    for c in candidates:
        if c.get("status") != "rejected":
            continue
        for name in (c.get("verification") or {}).get("failed", []):
            rejects_by_check[name] += 1

    raw_outcomes = [o for o in store.read(store.OUTCOMES)
                    if o.get("status") == "scored"]

    rows = []
    for o in raw_outcomes:
        if o.get("candidate_id") not in episode_ids:
            continue
        row = _regrade(o, claim_of.get(o.get("candidate_id")))
        if row:
            rows.append(row)

    buckets: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        buckets[row["signal"]][row["claim"] or "unknown"][row["horizon_hours"]].append(row)

    scorecard: dict = {}
    for signal, by_claim in sorted(buckets.items()):
        _, unit = MEASURE.get(signal, ("", ""))
        scorecard[signal] = {"unit": unit, "claims": {}}
        for claim, by_horizon in sorted(by_claim.items()):
            horizons = {}
            for horizon, group in sorted(by_horizon.items()):
                verdicts = Counter(r["verdict"] for r in group)
                decisive = verdicts["right"] + verdicts["wrong"]
                measures = [r["measure"] for r in group if r["measure"] is not None]
                horizons[horizon] = {
                    "episodes_graded": len(group),
                    "right": verdicts["right"],
                    "wrong": verdicts["wrong"],
                    "no_value": verdicts["no_value"],
                    "subjects": len({r["subject"] for r in group}),
                    # Denominator is decisive calls only. A call that provably
                    # said nothing is not evidence either way, and is shown in
                    # its own column rather than quietly inflating a rate.
                    "hit_rate": round(verdicts["right"] / decisive, 4) if decisive else None,
                    "mean_measure": round(sum(measures) / len(measures), 3)
                    if measures else None,
                }
            scorecard[signal]["claims"][claim] = horizons

    latest: dict[str, dict] = {}
    for c in candidates:
        subject = c.get("ticker") or c.get("coin") or c.get("venue") or c.get("status", "?")
        latest[f"{c.get('signal', '?')}:{subject}"] = c

    summary = episodes.summarise(candidates)

    return {
        "generated_at": max((c.get("detected_at") or 0 for c in candidates), default=0),
        "captures": len(candidates),
        "status_counts": dict(by_status),
        "rejections_by_check": dict(rejects_by_check),
        "episodes": summary,
        "grading": {
            "raw_outcomes": len(raw_outcomes),
            "after_deduplication": len(rows),
            "note": "One situation is graded once. The rest of the log is kept "
                    "and readable; it is observation, not prediction.",
        },
        "scorecard": scorecard,
        "latest": latest,
        "cost_floor_bps": round((config.COSTS.fixed_round_trip + config.EDGE_MARGIN) * 10_000),
    }


def to_markdown(report: dict) -> str:
    lines = ["## Scorecard", ""]
    counts = report["status_counts"]

    lines.append(f"`{report['captures']}` candidate records across all captures.")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    order = ["tradeable", "fired", "not_fillable", "clean_no_trade",
             "market_summary", "rejected", "no_reference", "error"]
    for status in order + [s for s in counts if s not in order]:
        if status in counts:
            lines.append(f"| {status} | {counts[status]} |")

    ep = report["episodes"]
    grading = report["grading"]
    lines += ["", "### How many calls is that, really", "",
              f"`{ep['claimable_records']}` records that make a claim, across "
              f"`{ep['distinct_subjects']}` distinct subjects, collapse to "
              f"**`{ep['episodes']}` episodes** - the same situation was "
              f"re-observed `{ep['repetition_factor']}x` on average.",
              "",
              f"So `{grading['raw_outcomes']}` raw graded outcomes become "
              f"**`{grading['after_deduplication']}`** real calls. Every number "
              "below uses the second figure."]

    if report["rejections_by_check"]:
        lines += ["", "### What the guard caught", "",
                  "| Check | Rejections |", "|---|---:|"]
        for name, n in sorted(report["rejections_by_check"].items(),
                              key=lambda kv: -kv[1]):
            lines.append(f"| `{name}` | {n} |")

    if report["scorecard"]:
        lines += ["", "### Outcomes", "",
                  "Split by what was actually claimed. **act** says the trade "
                  "pays; **abstain** says staying out is right. They are "
                  "different assertions and never share a hit rate."]
        for signal, block in report["scorecard"].items():
            lines += ["", f"#### {signal} _({block['unit']})_", "",
                      "| Claim | Horizon | Calls | Subjects | Right | Wrong | "
                      "No value | Hit rate | Mean |",
                      "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
            for claim, horizons in block["claims"].items():
                for horizon, s in horizons.items():
                    hit = f"{s['hit_rate'] * 100:.0f}%" if s["hit_rate"] is not None else "-"
                    # A growth ratio must never be rendered with a P&L sign.
                    # "+1.4" reads as a gain; the number means "1.4x the market".
                    if s["mean_measure"] is None:
                        mean = "-"
                    elif signal == "meta":
                        mean = f"{s['mean_measure']:.2f}x"
                    else:
                        mean = f"{s['mean_measure']:+.0f}bps"
                    lines.append(
                        f"| {claim} | {horizon}h | {s['episodes_graded']} | "
                        f"{s['subjects']} | {s['right']} | {s['wrong']} | "
                        f"{s['no_value']} | {hit} | {mean} |")
    else:
        lines += ["", "_No outcomes graded yet - the first ones land "
                  f"{config.BASIS_HORIZONS_HOURS[0]}h after the first capture._"]

    lines += ["", f"Cost floor: `{report['cost_floor_bps']}bps` round trip. "
              "A gap under that is not a trade, and is logged as such."]
    return "\n".join(lines)


def main() -> int:
    report = build()
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(os.path.join(config.DATA_DIR, "board.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    print(to_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
