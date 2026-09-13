"""
Signal 03 - launchpad rotation, a.k.a. "what is the meta".

The crypto-twitter question "what is the meta right now" has a boring,
measurable answer: **follow the fees.** Attention shows up as launch volume,
launch volume shows up as protocol revenue, and revenue is published daily for
every launchpad in existence. Rotation between venues is therefore a number,
not a vibe.

One call to DefiLlama returns yesterday's and the day before's fees for 152
launchpads, plus a 7-day total. That is enough to compute, with no history of
our own:

    share       this venue's cut of all launchpad fees today
    share_delta how that cut moved versus yesterday
    momentum    today against this venue's own 7-day daily average

A venue taking share while running hot against its own baseline is the meta
moving. A venue bleeding share is the meta leaving. A venue with real volume
and no 7-day history is brand new, which is the most interesting case of all
and the one a pure momentum screen would miss.

What this does NOT claim: that rotation is tradeable. It claims rotation is
*happening*, and then checks a day later whether it stuck. A venue that spikes
for one day and dies is noise; a venue that takes share and holds it is a trend.
Scoring the difference is the entire point.
"""

from __future__ import annotations

import hashlib
import time

from ..sources import get

SIGNAL = "meta"
VERSION = 1

HORIZONS_HOURS = [24, 72]

DEFILLAMA_FEES = "https://api.llama.fi/overview/fees"

# --------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------

# Venues below this are hobby projects; their percentage swings are meaningless.
MIN_DAY_FEES_USD = 25_000

# A venue must clear this before a rotation call is worth making.
MIN_SIGNAL_FEES_USD = 100_000

# Share of the whole launchpad market, in percentage points, gained or lost
# day over day.
SHARE_SHIFT_PP = 5.0

# Today against the venue's own 7-day daily average.
MOMENTUM_HOT = 3.0
MOMENTUM_COLD = 0.33

# A day more than this many times the weekly average is usually a backfill or a
# reporting artifact, not a real day.
MAX_PLAUSIBLE_MOMENTUM = 20.0


def _candidate_id(name: str, ts: int) -> str:
    return hashlib.sha1(f"{SIGNAL}:{name}:{ts}".encode()).hexdigest()[:16]


def _launchpads() -> list[dict]:
    data = get(
        DEFILLAMA_FEES,
        params={
            "excludeTotalDataChart": "true",
            "excludeTotalDataChartBreakdown": "true",
        },
    )
    protocols = (data or {}).get("protocols") or []
    rows = []

    for p in protocols:
        if "launchpad" not in str(p.get("category", "")).lower():
            continue
        try:
            today = float(p.get("total24h") or 0)
            yesterday = float(p.get("total48hto24h") or 0)
            week = float(p.get("total7d") or 0)
        except (TypeError, ValueError):
            continue

        rows.append({
            "name": p.get("displayName") or p.get("name"),
            "slug": p.get("slug"),
            "chains": p.get("chains") or [],
            "fees_24h": today,
            "fees_prev_24h": yesterday,
            "fees_7d": week,
            "daily_average_7d": week / 7 if week else 0.0,
        })

    return rows


def _verify(row: dict) -> tuple[bool, list[str]]:
    failures = []

    if row["fees_24h"] < MIN_DAY_FEES_USD:
        failures.append("too_small")
    if row["fees_24h"] < 0 or row["fees_7d"] < 0:
        failures.append("negative_fees")
    if row["daily_average_7d"] > 0:
        momentum = row["fees_24h"] / row["daily_average_7d"]
        if momentum > MAX_PLAUSIBLE_MOMENTUM:
            # 20x the weekly average in one day is a reporting artifact far more
            # often than it is a real day.
            failures.append("implausible_momentum")

    return (not failures), failures


def _classify(row: dict, share: float, prev_share: float) -> tuple[str, str] | None:
    if row["fees_24h"] < MIN_SIGNAL_FEES_USD:
        return None

    share_delta = share - prev_share
    average = row["daily_average_7d"]

    # A venue doing real money with essentially no week behind it is new.
    # "No week behind it" means the 7-day total is barely more than today -
    # a real week of operation would be several times a single day.
    if average <= 0 or row["fees_7d"] <= row["fees_24h"] * 1.5:
        return "new_entrant", "the meta has somewhere new to go"

    momentum = row["fees_24h"] / average

    # Share alone lies when the whole market is shrinking. On the first live
    # capture the launchpad market fell 16.6% in a day, and Pons "gained 5.2
    # points of share" while its own revenue ran at 0.81x its weekly average -
    # it did not win anything, it shrank more slowly than everyone else.
    # So a share gain only counts as rotation IN if the venue is not itself
    # contracting, and a share loss only counts as rotation OUT if it is.
    if (share_delta >= SHARE_SHIFT_PP and momentum >= 1.0) or momentum >= MOMENTUM_HOT:
        return "rotation_in", "attention and launch volume moving toward this venue"
    if (share_delta <= -SHARE_SHIFT_PP and momentum <= 1.0) or momentum <= MOMENTUM_COLD:
        return "rotation_out", "attention and launch volume leaving this venue"
    return None


def detect() -> list[dict]:
    now = int(time.time())
    records: list[dict] = []

    try:
        rows = _launchpads()
    except RuntimeError as exc:
        return [{
            "candidate_id": _candidate_id("ALL", now),
            "signal": SIGNAL, "version": VERSION, "detected_at": now,
            "status": "error", "reason": f"fee fetch failed: {exc}",
        }]

    tracked = []
    for row in rows:
        ok, failures = _verify(row)
        if ok:
            tracked.append(row)
        elif "too_small" not in failures:
            # Small venues are not findings. Broken numbers on a big one are.
            records.append({
                "candidate_id": _candidate_id(row["name"] or "?", now),
                "signal": SIGNAL, "version": VERSION, "detected_at": now,
                "venue": row["name"], "status": "rejected",
                "reason": "failed " + ",".join(failures),
                "fees_24h": round(row["fees_24h"]),
            })

    # The denominator is built from VERIFIED venues only. A rejected number
    # left in the total silently poisons every share in the table: one bogus
    # $4M day inflates the market 30% and every honest venue appears to have
    # "lost 16 points of share" overnight. Rejected data must not vote.
    market_today = sum(r["fees_24h"] for r in tracked)
    market_prev = sum(r["fees_prev_24h"] for r in tracked)

    if market_today <= 0:
        records.append({
            "candidate_id": _candidate_id("ALL", now),
            "signal": SIGNAL, "version": VERSION, "detected_at": now,
            "status": "error", "reason": "no verified launchpad fees reported",
        })
        return records

    ranked = sorted(tracked, key=lambda r: r["fees_24h"], reverse=True)

    records.append({
        "candidate_id": _candidate_id("MARKET", now),
        "signal": SIGNAL, "version": VERSION, "detected_at": now,
        "status": "market_summary",
        "tracked_venues": len(tracked),
        "market_fees_24h": round(market_today),
        "market_fees_prev_24h": round(market_prev),
        "market_change_pct": round((market_today / market_prev - 1) * 100, 2)
        if market_prev else None,
        "leaderboard": [
            {"venue": r["name"],
             "fees_24h": round(r["fees_24h"]),
             "share_pct": round(r["fees_24h"] / market_today * 100, 2),
             "chains": r["chains"][:3]}
            for r in ranked[:6]
        ],
        "reason": f"{len(tracked)} venues, ${market_today / 1e6:.2f}M in launchpad "
                  f"fees today, led by {ranked[0]['name'] if ranked else 'nobody'}",
    })

    for row in tracked:
        share = row["fees_24h"] / market_today * 100
        prev_share = (row["fees_prev_24h"] / market_prev * 100) if market_prev else 0.0

        verdict = _classify(row, share, prev_share)
        if verdict is None:
            continue
        kind, read = verdict

        momentum = (row["fees_24h"] / row["daily_average_7d"]
                    if row["daily_average_7d"] else None)

        records.append({
            "candidate_id": _candidate_id(row["name"] or "?", now),
            "signal": SIGNAL, "version": VERSION, "detected_at": now,
            "venue": row["name"],
            "slug": row["slug"],
            "chains": row["chains"][:3],
            "status": "fired",
            "kind": kind,
            "read": read,
            "fees_24h": round(row["fees_24h"]),
            "fees_prev_24h": round(row["fees_prev_24h"]),
            "fees_7d": round(row["fees_7d"]),
            "entry_share_pct": round(share, 3),
            "prev_share_pct": round(prev_share, 3),
            "share_delta_pp": round(share - prev_share, 3),
            "momentum": None if momentum is None else round(momentum, 2),
            "reason": f"{kind}: {share:.1f}% of launchpad fees "
                      f"({share - prev_share:+.1f}pp)"
                      + (f", {momentum:.1f}x its weekly average" if momentum else ""),
        })

    return records


def score(candidate: dict, horizon_hours: int) -> dict | None:
    """
    Did the rotation stick?

    A venue that spikes for a day and dies is noise. A venue that takes share
    and holds it is a trend. The only honest way to tell them apart is to come
    back later and look, which is what this does.
    """
    venue = candidate.get("venue")
    if not venue or candidate.get("status") != "fired":
        return None

    try:
        rows = _launchpads()
    except RuntimeError as exc:
        return {
            "candidate_id": candidate["candidate_id"], "signal": SIGNAL,
            "venue": venue, "horizon_hours": horizon_hours,
            "scored_at": int(time.time()),
            "status": "ungradeable", "reason": f"fee fetch failed: {exc}",
        }

    # Verify before totalling, exactly as detection does. Grading a call
    # against a contaminated denominator would manufacture its own verdict.
    verified = [r for r in rows if _verify(r)[0]]
    market_today = sum(r["fees_24h"] for r in verified)
    row = next((r for r in verified if r["name"] == venue), None)

    if row is None or market_today <= 0:
        return {
            "candidate_id": candidate["candidate_id"], "signal": SIGNAL,
            "venue": venue, "horizon_hours": horizon_hours,
            "scored_at": int(time.time()),
            "status": "ungradeable", "reason": "venue no longer reported",
        }

    share = row["fees_24h"] / market_today * 100
    entry_share = candidate.get("entry_share_pct") or 0.0
    change_pp = share - entry_share

    kind = candidate.get("kind")
    if kind in ("rotation_in", "new_entrant"):
        held = change_pp >= 0
    elif kind == "rotation_out":
        held = change_pp <= 0
    else:
        held = None

    return {
        "candidate_id": candidate["candidate_id"],
        "signal": SIGNAL,
        "venue": venue,
        "kind": kind,
        "horizon_hours": horizon_hours,
        "scored_at": int(time.time()),
        "status": "scored",
        "entry_share_pct": round(entry_share, 3),
        "exit_share_pct": round(share, 3),
        "share_change_pp": round(change_pp, 3),
        # Signed so positive always means the call was right.
        "edge_bps": round((change_pp if kind != "rotation_out" else -change_pp) * 100),
        "correct": held,
        "profitable": held,
        "fees_then": candidate.get("fees_24h"),
        "fees_now": round(row["fees_24h"]),
    }
