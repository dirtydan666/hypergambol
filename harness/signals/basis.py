"""
Signal 01 - tokenized equity basis.

Detect: a verified on-chain price that differs from the equity reference by
more than it costs to trade, at a size the router will actually fill.

Score: did the gap converge, and would a delta-neutral entry have paid after
costs? Graded at 4h, 24h and 72h.

This is deliberately the narrowest signal in the system. It is here to prove
the harness, and because every later signal - smart-money wallets, launchpad
rotation - plugs into the same detect/verify/log/score contract.
"""

from __future__ import annotations

import hashlib
import time

from .. import config, store
from ..sources import (
    EquityQuote,
    coingecko_prices,
    equity_quote,
    hyperliquid_mids,
    jupiter_buy_quote,
    pools_for,
)
from ..verify import verify_price

SIGNAL = "basis"
VERSION = 1


def _candidate_id(ticker: str, ts: int) -> str:
    return hashlib.sha1(f"{SIGNAL}:{ticker}:{ts}".encode()).hexdigest()[:16]


def detect() -> list[dict]:
    """
    Returns one record per instrument - tradeable, rejected or clean.

    Everything gets logged. The rejects are the proof the guard works, and the
    clean-but-flat rows are how we later show that most nights there is nothing
    to do, which is the claim that makes the tradeable nights believable.
    """
    now = int(time.time())
    records: list[dict] = []

    solana = [i for i in config.UNIVERSE if i.chain == "solana"]
    try:
        provider = coingecko_prices("solana", [i.mint for i in solana])
    except RuntimeError:
        provider = {}

    try:
        mids = hyperliquid_mids()
    except RuntimeError:
        mids = {}

    for inst in config.UNIVERSE:
        record = {
            "candidate_id": _candidate_id(inst.ticker, now),
            "signal": SIGNAL,
            "version": VERSION,
            "detected_at": now,
            "ticker": inst.ticker,
            "chain": inst.chain,
            "mint": inst.mint,
        }

        try:
            snapshot = pools_for(inst.chain, inst.mint)
        except RuntimeError as exc:
            record.update(status="error", reason=f"pool fetch failed: {exc}")
            records.append(record)
            continue

        verified = verify_price(
            snapshot,
            provider.get(inst.mint.lower()),
            _previous(inst.mint, now),
        )
        record["verification"] = verified.as_dict()

        if not verified.ok:
            record.update(status="rejected", reason="failed " + ",".join(verified.failed_checks))
            records.append(record)
            continue

        reference = _reference_price(inst, mids)
        if reference is None:
            record.update(status="no_reference", reason="no equity or perp reference available")
            records.append(record)
            continue

        record["reference"] = reference
        gross_basis = verified.price / reference["price"] - 1
        record["gross_basis"] = round(gross_basis, 6)
        record["gross_basis_bps"] = round(gross_basis * 10_000)

        cost_floor = config.COSTS.fixed_round_trip + config.EDGE_MARGIN
        record["cost_floor"] = round(cost_floor, 6)

        if abs(gross_basis) < cost_floor:
            record.update(status="clean_no_trade",
                          reason=f"{abs(gross_basis) * 100:.2f}% gap under "
                                 f"{cost_floor * 100:.2f}% cost floor")
            records.append(record)
            continue

        # Only now - once a gap has survived verification and cleared the cost
        # floor on paper - is it worth spending a router call to see whether it
        # is fillable. An aggregator mid is not a fill.
        record["quotes"] = _executable_quotes(inst, reference["price"], gross_basis)
        tradeable = [q for q in record["quotes"] if q["net_edge"] > 0]

        if tradeable:
            best = max(tradeable, key=lambda q: q["net_edge"])
            record.update(
                status="tradeable",
                best_size_usd=best["size_usd"],
                net_edge=best["net_edge"],
                net_edge_bps=round(best["net_edge"] * 10_000),
                reason=f"{gross_basis * 100:+.2f}% gross survives at ${best['size_usd']:,.0f}",
            )
        else:
            record.update(
                status="not_fillable",
                reason="gap clears cost floor on mid price but not on an executable quote",
            )

        records.append(record)

    return records


def _previous(mint: str, now: int) -> dict | None:
    """Our own last published price for this token, with its age."""
    last = store.last_verified(mint)
    if not last or not last.get("ts"):
        return None
    return {"price": last["price"], "age_seconds": max(0, now - last["ts"])}


def _reference_price(inst, mids: dict) -> dict | None:
    """
    The thing the token is supposed to track.

    Perp mid is preferred when available: it is a live 24/7 market, it is the
    leg you would actually short, and it does not go stale at 4pm. The equity
    quote is the fallback and the sanity anchor.
    """
    if inst.perp and inst.perp in mids:
        return {"kind": "perp_mid", "price": mids[inst.perp], "source": f"hyperliquid:{inst.perp}"}

    try:
        eq: EquityQuote | None = equity_quote(inst.ticker)
    except RuntimeError:
        eq = None
    if eq:
        return {"kind": "equity", "price": eq.price, "source": eq.source, "quote_ts": eq.quote_ts}

    return None


def _executable_quotes(inst, reference_price: float, gross_basis: float) -> list[dict]:
    """
    A discount is only tradeable if you can buy the token at the discount.
    Ask the router what it would actually fill, at each size.
    """
    out = []
    for size in config.QUOTE_SIZES_USD:
        try:
            quote = jupiter_buy_quote(inst.mint, inst.decimals, size)
        except RuntimeError:
            quote = None
        if quote is None:
            out.append({"size_usd": size, "error": "no route", "net_edge": -1.0})
            continue

        # Effective basis at the fill price, not the mid.
        effective_basis = quote.effective_price / reference_price - 1
        # A discount is the profitable direction for a spot buy; a premium
        # would be traded the other way round, which needs a borrow we do not
        # have. So only discounts count for now.
        realizable = -effective_basis if gross_basis < 0 else 0.0
        net_edge = realizable - config.COSTS.fixed_round_trip

        entry = quote.as_dict()
        entry.update(
            effective_basis=round(effective_basis, 6),
            net_edge=round(net_edge, 6),
        )
        out.append(entry)
    return out


def score(candidate: dict, horizon_hours: int) -> dict | None:
    """
    Grade a past candidate. Convergence is measured against the same reference
    kind it was detected on, so we are not grading a perp signal with an
    equity close.
    """
    ticker = candidate["ticker"]
    inst = next((i for i in config.UNIVERSE if i.ticker == ticker), None)
    if inst is None:
        return None

    try:
        snapshot = pools_for(inst.chain, inst.mint)
        provider = coingecko_prices("solana", [inst.mint]) if inst.chain == "solana" else {}
    except RuntimeError as exc:
        return {"error": f"scoring fetch failed: {exc}"}

    verified = verify_price(
        snapshot,
        provider.get(inst.mint.lower()),
        _previous(inst.mint, int(time.time())),
    )
    if not verified.ok:
        # Cannot grade against a price we would not have published.
        return {
            "candidate_id": candidate["candidate_id"],
            "horizon_hours": horizon_hours,
            "scored_at": int(time.time()),
            "status": "ungradeable",
            "reason": "failed " + ",".join(verified.failed_checks),
        }

    mids = {}
    if inst.perp:
        try:
            mids = hyperliquid_mids()
        except RuntimeError:
            mids = {}
    reference = _reference_price(inst, mids)
    if reference is None:
        return {
            "candidate_id": candidate["candidate_id"],
            "horizon_hours": horizon_hours,
            "scored_at": int(time.time()),
            "status": "ungradeable",
            "reason": "no reference at scoring time",
        }

    entry_basis = candidate.get("gross_basis")
    exit_basis = verified.price / reference["price"] - 1

    converged = abs(exit_basis) < abs(entry_basis) if entry_basis is not None else None
    captured = (abs(entry_basis) - abs(exit_basis)) if entry_basis is not None else None
    net = (captured - config.COSTS.fixed_round_trip) if captured is not None else None

    return {
        "candidate_id": candidate["candidate_id"],
        "signal": SIGNAL,
        "ticker": ticker,
        "horizon_hours": horizon_hours,
        "scored_at": int(time.time()),
        "status": "scored",
        "entry_status": candidate.get("status"),
        "entry_basis_bps": None if entry_basis is None else round(entry_basis * 10_000),
        "exit_basis_bps": round(exit_basis * 10_000),
        "converged": converged,
        "captured_bps": None if captured is None else round(captured * 10_000),
        "net_after_costs_bps": None if net is None else round(net * 10_000),
        "profitable": None if net is None else net > 0,
    }
