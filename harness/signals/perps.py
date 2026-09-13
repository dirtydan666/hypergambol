"""
Signal 02 - crowded positioning on Hyperliquid perps.

The hypothesis: when the cost of holding one side of a trade gets extreme,
that side is crowded, and crowded trades unwind. Funding is the price of
crowding, so it is the thing to watch.

The catch that shapes this whole module: **Hyperliquid clamps funding.**
In a live sample of 43 liquid markets, 33 of them sat at exactly 0.0000125/hr
- the clamp - and the median, p25, p75 and p95 were all that identical number.
A screener that ranks markets by funding therefore produces a 33-way tie and
tells you nothing.

So the signal is not "high funding". It is "funding that escaped the clamp":

  crowded_long   funding pushed ABOVE the clamp - long demand strong enough to
                 break through a rate ceiling. Rare. Expect weakness.
  crowded_short  funding went NEGATIVE - shorts are paying longs to hold the
                 other side. Rarer still (3 of 43). Expect strength.

Everything between those two tails is the clamp, and the clamp is not
information. That is the difference between a signal and a leaderboard.
"""

from __future__ import annotations

import hashlib
import time

from ..sources import post, HYPERLIQUID

SIGNAL = "perps"
VERSION = 1

HORIZONS_HOURS = [4, 24, 72]

# --------------------------------------------------------------------------
# Thresholds
# --------------------------------------------------------------------------

# Hyperliquid's hourly funding clamp. Confirmed live: the modal value across
# liquid markets, and equal to the median, p25, p75 and p95 simultaneously.
FUNDING_CLAMP = 0.0000125

# How far past the clamp funding must go before long crowding is real.
CLAMP_BREAK_MULTIPLE = 1.5

# Liquidity floors. Below these, funding is noise from a market nobody trades.
MIN_OPEN_INTEREST_USD = 5_000_000
MIN_DAY_VOLUME_USD = 1_000_000

# Data-sanity bounds.
MAX_MARK_ORACLE_DIVERGENCE = 0.01   # 1%
MAX_PLAUSIBLE_FUNDING = 0.01        # 1%/hr would be extraordinary


def _candidate_id(coin: str, ts: int) -> str:
    return hashlib.sha1(f"{SIGNAL}:{coin}:{ts}".encode()).hexdigest()[:16]


def _market_rows() -> list[dict]:
    """One row per perp market, numbers coerced, USD-denominated where useful."""
    data = post(HYPERLIQUID, json={"type": "metaAndAssetCtxs"})
    if not isinstance(data, list) or len(data) < 2:
        raise RuntimeError("unexpected metaAndAssetCtxs shape")

    universe = (data[0] or {}).get("universe", [])
    contexts = data[1] or []
    rows = []

    for asset, ctx in zip(universe, contexts):
        if not ctx:
            continue
        try:
            mark = float(ctx["markPx"])
            rows.append({
                "coin": asset.get("name"),
                "funding": float(ctx["funding"]),
                "mark": mark,
                "oracle": float(ctx["oraclePx"]),
                "mid": float(ctx.get("midPx") or mark),
                "premium": float(ctx.get("premium") or 0.0),
                "open_interest_usd": float(ctx["openInterest"]) * mark,
                "day_volume_usd": float(ctx["dayNtlVlm"]),
                "day_change": mark / float(ctx["prevDayPx"]) - 1
                if float(ctx.get("prevDayPx") or 0) else None,
            })
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue

    return rows


def _verify(row: dict) -> tuple[bool, list[str]]:
    """Same spirit as the basis guard: refuse to act on a number we don't trust."""
    failures = []

    if row["open_interest_usd"] < MIN_OPEN_INTEREST_USD:
        failures.append("open_interest")
    if row["day_volume_usd"] < MIN_DAY_VOLUME_USD:
        failures.append("volume")
    if row["mark"] <= 0 or row["oracle"] <= 0:
        failures.append("price_sanity")
    elif abs(row["mark"] / row["oracle"] - 1) > MAX_MARK_ORACLE_DIVERGENCE:
        failures.append("mark_oracle_divergence")
    if abs(row["funding"]) > MAX_PLAUSIBLE_FUNDING:
        failures.append("funding_sanity")

    return (not failures), failures


def _classify(row: dict) -> tuple[str, str] | None:
    """Returns (kind, expected_direction) or None when the market is at the clamp."""
    funding = row["funding"]
    if funding < 0:
        return "crowded_short", "up"
    if funding >= FUNDING_CLAMP * CLAMP_BREAK_MULTIPLE:
        return "crowded_long", "down"
    return None


def detect() -> list[dict]:
    now = int(time.time())
    records: list[dict] = []

    try:
        rows = _market_rows()
    except RuntimeError as exc:
        return [{
            "candidate_id": _candidate_id("ALL", now),
            "signal": SIGNAL, "version": VERSION, "detected_at": now,
            "status": "error", "reason": str(exc),
        }]

    liquid = []
    for row in rows:
        ok, failures = _verify(row)
        if ok:
            liquid.append(row)
        elif failures and failures != ["open_interest"] and failures != ["volume"] \
                and failures != ["open_interest", "volume"]:
            # Illiquid markets are not worth a log line; genuinely broken data is.
            records.append({
                "candidate_id": _candidate_id(row["coin"], now),
                "signal": SIGNAL, "version": VERSION, "detected_at": now,
                "coin": row["coin"], "status": "rejected",
                "reason": "failed " + ",".join(failures),
                "funding": row["funding"], "mark": row["mark"],
            })

    at_clamp = sum(1 for r in liquid if r["funding"] == FUNDING_CLAMP)
    negative = sum(1 for r in liquid if r["funding"] < 0)

    # One baseline row per capture. Cheap, and it is what lets us say later
    # how unusual any given night was.
    records.append({
        "candidate_id": _candidate_id("MARKET", now),
        "signal": SIGNAL, "version": VERSION, "detected_at": now,
        "status": "market_summary",
        "liquid_markets": len(liquid),
        "at_clamp": at_clamp,
        "negative_funding": negative,
        "total_open_interest_usd": round(sum(r["open_interest_usd"] for r in liquid)),
        "total_day_volume_usd": round(sum(r["day_volume_usd"] for r in liquid)),
        "reason": f"{len(liquid)} liquid markets, {at_clamp} pinned at the funding clamp",
    })

    for row in liquid:
        verdict = _classify(row)
        if verdict is None:
            continue
        kind, direction = verdict

        records.append({
            "candidate_id": _candidate_id(row["coin"], now),
            "signal": SIGNAL, "version": VERSION, "detected_at": now,
            "coin": row["coin"],
            "status": "fired",
            "kind": kind,
            "expected_direction": direction,
            "funding": row["funding"],
            "funding_vs_clamp": round(row["funding"] / FUNDING_CLAMP, 3),
            "annualised_funding": round(row["funding"] * 24 * 365, 4),
            "entry_mark": row["mark"],
            "premium": row["premium"],
            "open_interest_usd": round(row["open_interest_usd"]),
            "day_volume_usd": round(row["day_volume_usd"]),
            "day_change": None if row["day_change"] is None else round(row["day_change"], 5),
            "reason": f"{kind}: funding {row['funding'] * 24 * 365 * 100:.1f}%/yr, "
                      f"{row['funding'] / FUNDING_CLAMP:.2f}x the clamp",
        })

    return records


def score(candidate: dict, horizon_hours: int) -> dict | None:
    """
    Did the crowded side actually unwind? Graded on the mark price, in the
    direction the signal claimed, net of nothing - this is a directional call,
    so the honest measure is simply whether price went the predicted way.
    """
    coin = candidate.get("coin")
    if not coin or candidate.get("status") != "fired":
        return None

    try:
        rows = _market_rows()
    except RuntimeError as exc:
        return {
            "candidate_id": candidate["candidate_id"], "signal": SIGNAL,
            "horizon_hours": horizon_hours, "scored_at": int(time.time()),
            "status": "ungradeable", "reason": str(exc),
        }

    row = next((r for r in rows if r["coin"] == coin), None)
    if row is None:
        return {
            "candidate_id": candidate["candidate_id"], "signal": SIGNAL,
            "coin": coin, "horizon_hours": horizon_hours,
            "scored_at": int(time.time()),
            "status": "ungradeable", "reason": "market no longer listed",
        }

    ok, failures = _verify(row)
    if not ok:
        return {
            "candidate_id": candidate["candidate_id"], "signal": SIGNAL,
            "coin": coin, "horizon_hours": horizon_hours,
            "scored_at": int(time.time()),
            "status": "ungradeable", "reason": "failed " + ",".join(failures),
        }

    entry = candidate.get("entry_mark")
    if not entry:
        return None

    ret = row["mark"] / entry - 1
    expected_down = candidate.get("expected_direction") == "down"
    correct = (ret < 0) if expected_down else (ret > 0)

    return {
        "candidate_id": candidate["candidate_id"],
        "signal": SIGNAL,
        "coin": coin,
        "kind": candidate.get("kind"),
        "horizon_hours": horizon_hours,
        "scored_at": int(time.time()),
        "status": "scored",
        "entry_mark": entry,
        "exit_mark": row["mark"],
        "return_bps": round(ret * 10_000),
        "expected_direction": candidate.get("expected_direction"),
        # Signed so that positive always means the call was right, whichever
        # way it pointed. This is the number the scorecard averages.
        "edge_bps": round((-ret if expected_down else ret) * 10_000),
        "correct": correct,
        "profitable": correct,
        "funding_then": candidate.get("funding"),
        "funding_now": row["funding"],
        "funding_normalised": abs(row["funding"] - FUNDING_CLAMP) < abs(
            candidate.get("funding", 0) - FUNDING_CLAMP),
    }
