"""
Renders the scorecard - the thing that makes this credible rather than loud.

    python -m harness.report

Writes data/board.json (for the site) and prints a markdown scorecard for the
repo README. Reports rejection counts as prominently as hit rates, because
"we threw out four prints that looked like money" is the claim nobody else
in this category can make.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from . import config, store


def build() -> dict:
    candidates = list(store.read(store.CANDIDATES))
    outcomes = [o for o in store.read(store.OUTCOMES) if o.get("status") == "scored"]

    by_status = Counter(c.get("status") for c in candidates)
    rejects_by_check = Counter()
    for c in candidates:
        if c.get("status") != "rejected":
            continue
        for name in (c.get("verification") or {}).get("failed", []):
            rejects_by_check[name] += 1

    by_horizon: dict[int, list[dict]] = defaultdict(list)
    for o in outcomes:
        by_horizon[o["horizon_hours"]].append(o)

    scorecard = {}
    for horizon, rows in sorted(by_horizon.items()):
        converged = [r for r in rows if r.get("converged")]
        profitable = [r for r in rows if r.get("profitable")]
        nets = [r["net_after_costs_bps"] for r in rows if r.get("net_after_costs_bps") is not None]
        scorecard[horizon] = {
            "graded": len(rows),
            "converged": len(converged),
            "convergence_rate": round(len(converged) / len(rows), 4) if rows else None,
            "profitable_after_costs": len(profitable),
            "hit_rate": round(len(profitable) / len(rows), 4) if rows else None,
            "mean_net_bps": round(sum(nets) / len(nets), 1) if nets else None,
        }

    latest: dict[str, dict] = {}
    for c in candidates:
        # Signals name their subject differently - basis has a ticker, perps a
        # coin, and the market-summary row has neither.
        subject = c.get("ticker") or c.get("coin") or c.get("status", "?")
        latest[f"{c.get('signal', '?')}:{subject}"] = c

    return {
        "generated_at": max((c["detected_at"] for c in candidates), default=0),
        "captures": len(candidates),
        "status_counts": dict(by_status),
        "rejections_by_check": dict(rejects_by_check),
        "scorecard": scorecard,
        "latest": latest,
        "cost_floor_bps": round((config.COSTS.fixed_round_trip + config.EDGE_MARGIN) * 10_000),
    }


def to_markdown(report: dict) -> str:
    lines = ["## Scorecard", ""]
    counts = report["status_counts"]
    total = report["captures"]

    lines.append(f"`{total}` candidate records across all captures.")
    lines.append("")
    lines.append("| Status | Count |")
    lines.append("|---|---:|")
    # Preferred order first, then anything a newer signal has invented, so a
    # new signal's activity never silently vanishes from the scorecard.
    order = ["tradeable", "fired", "not_fillable", "clean_no_trade",
             "market_summary", "rejected", "no_reference", "error"]
    for status in order + [s for s in counts if s not in order]:
        if status in counts:
            lines.append(f"| {status} | {counts[status]} |")

    if report["rejections_by_check"]:
        lines += ["", "### What the guard caught", "",
                  "| Check | Rejections |", "|---|---:|"]
        for name, n in sorted(report["rejections_by_check"].items(),
                              key=lambda kv: -kv[1]):
            lines.append(f"| `{name}` | {n} |")

    if report["scorecard"]:
        lines += ["", "### Outcomes", "",
                  "| Horizon | Graded | Converged | Hit rate after costs | Mean net |",
                  "|---:|---:|---:|---:|---:|"]
        for horizon, s in report["scorecard"].items():
            hit = f"{s['hit_rate'] * 100:.0f}%" if s["hit_rate"] is not None else "-"
            conv = f"{s['convergence_rate'] * 100:.0f}%" if s["convergence_rate"] is not None else "-"
            net = f"{s['mean_net_bps']:+.0f}bps" if s["mean_net_bps"] is not None else "-"
            lines.append(f"| {horizon}h | {s['graded']} | {conv} | {hit} | {net} |")
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
