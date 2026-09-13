"""
The guard.

This module exists because of four false positives in two captures. Its job is
to answer one question about any on-chain price: would I bet money that this
number is real?

Every check records its own verdict, so rejected candidates stay in the log.
The rejections are the dataset that proves the guard works - and they are the
most credible thing this project can publish.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from . import config
from .sources import Pool, PoolSnapshot


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    value: float | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "value": None if self.value is None else round(self.value, 6),
        }


@dataclass
class VerifiedPrice:
    mint: str
    price: float | None = None
    checks: list[Check] = field(default_factory=list)
    pool_count: int = 0
    total_liquidity: float = 0.0
    total_volume_24h: float = 0.0
    dispersion: float | None = None
    providers: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.price is not None and all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[str]:
        return [c.name for c in self.checks if not c.passed]

    def as_dict(self) -> dict:
        return {
            "mint": self.mint,
            "price": None if self.price is None else round(self.price, 6),
            "ok": self.ok,
            "pool_count": self.pool_count,
            "total_liquidity": round(self.total_liquidity, 2),
            "total_volume_24h": round(self.total_volume_24h, 2),
            "dispersion": None if self.dispersion is None else round(self.dispersion, 6),
            "providers": {k: round(v, 6) for k, v in self.providers.items()},
            "checks": [c.as_dict() for c in self.checks],
            "failed": self.failed_checks,
        }


def _consensus_price(pools: list[Pool]) -> float:
    """
    Liquidity-weighted median across qualifying pools.
    Median, not mean: one stale pool must not move the print.
    """
    total = sum(p.liquidity_usd for p in pools)
    sample: list[float] = []
    for p in pools:
        weight = max(1, round(20 * p.liquidity_usd / total))
        sample.extend([p.price_usd] * weight)
    return median(sample)


def verify_price(
    snapshot: PoolSnapshot,
    provider_price: float | None = None,
    previous: dict | None = None,
) -> VerifiedPrice:
    """
    Four checks, in the order they caught real failures.

    1. depth        - enough qualifying pools to have an opinion at all
    2. dispersion   - the pools agree with each other
    3. provider     - an independent provider agrees with the pools
    4. drift        - the price is corroborated by the token's own 24h change
                      (this is the one that would have caught Apple)
    """
    result = VerifiedPrice(mint=snapshot.mint)
    qualifying = snapshot.qualifying

    result.pool_count = len(qualifying)
    result.total_liquidity = sum(p.liquidity_usd for p in qualifying)
    result.total_volume_24h = sum(p.volume_24h for p in qualifying)

    # 1. depth
    deep_single = (
        len(qualifying) == 1
        and qualifying[0].liquidity_usd >= config.SINGLE_POOL_MIN_LIQUIDITY_USD
    )
    enough = len(qualifying) >= config.MIN_POOLS_FOR_CONSENSUS or deep_single
    result.checks.append(Check(
        "depth",
        enough,
        f"{len(qualifying)} pools over ${config.MIN_POOL_LIQUIDITY_USD:,.0f}",
        float(len(qualifying)),
    ))
    if not enough:
        return result

    price = _consensus_price(qualifying)
    result.price = price
    result.providers["pools"] = price
    if provider_price:
        result.providers["coingecko"] = provider_price

    # 2. dispersion across pools
    lo = min(p.price_usd for p in qualifying)
    hi = max(p.price_usd for p in qualifying)
    dispersion = (hi - lo) / price if price else 1.0
    result.dispersion = dispersion
    result.checks.append(Check(
        "pool_dispersion",
        dispersion <= config.MAX_POOL_DISPERSION,
        f"{dispersion * 100:.2f}% spread across {len(qualifying)} pools "
        f"(limit {config.MAX_POOL_DISPERSION * 100:.1f}%)",
        dispersion,
    ))

    # 3. independent provider agreement
    if provider_price:
        disagreement = abs(price - provider_price) / provider_price
        result.checks.append(Check(
            "provider_agreement",
            disagreement <= config.MAX_PROVIDER_DISAGREEMENT,
            f"pools {price:.2f} vs provider {provider_price:.2f} "
            f"({disagreement * 100:.2f}% apart)",
            disagreement,
        ))
    else:
        # No second provider answered. Agreement across several deep pools is
        # weaker evidence than an independent source, but it is not nothing -
        # accept it and let the row stand as single-source.
        strong = len(qualifying) >= 3 and dispersion <= 0.002
        result.checks.append(Check(
            "provider_agreement", strong,
            f"no second provider; {len(qualifying)} pools within "
            f"{dispersion * 100:.2f}% of each other",
            dispersion,
        ))

    # 4. the Apple check
    result.checks.append(_drift_check(qualifying, price, previous))

    return result


def _drift_check(pools: list[Pool], price: float, previous: dict | None) -> Check:
    """
    The Apple check.

    Three numbers have to be mutually consistent: today's print, the token's
    own reported 24h change, and what this harness recorded last capture.

    Reconstruct where the token was 24 hours ago from the reported change. The
    true path between then and now has to pass somewhere between that point and
    the current price. If our previous observation sits well outside that band,
    then one of the two observations is wrong - and we do not get to decide
    which, so neither is tradeable.

    Apple, for real: previous capture $317.36, current $334, reported 24h change
    -0.50%. That puts the 24h-ago price at $335.70, so the band is roughly
    [$334, $335.70]. $317 is nowhere near it. Both price providers missed this
    because they shared the same bad state; the harness's own history did not.
    """
    changes = [p.change_24h for p in pools if p.change_24h is not None]
    if not changes:
        return Check("drift_corroboration", False, "no 24h change data to corroborate", None)

    reported = median(changes) / 100.0
    if reported <= -0.99:
        return Check("drift_corroboration", False, "degenerate 24h change", None)

    if not previous or not previous.get("price"):
        return Check(
            "drift_corroboration", True,
            "no prior observation yet - this check arms on the second capture", None,
        )

    elapsed_h = (previous.get("age_seconds") or 0) / 3600
    if not 0.25 <= elapsed_h <= 30:
        return Check(
            "drift_corroboration", True,
            f"prior observation {elapsed_h:.1f}h old - outside the 24h change window", None,
        )

    price_24h_ago = price / (1 + reported)
    lo, hi = sorted((price_24h_ago, price))
    band = config.MAX_UNEXPLAINED_24H_DRIFT * price

    prev_price = previous["price"]
    if lo - band <= prev_price <= hi + band:
        return Check(
            "drift_corroboration", True,
            f"prior {prev_price:.2f} sits inside the implied path "
            f"[{lo:.2f}, {hi:.2f}] +/- {band:.2f}", 0.0,
        )

    distance = (lo - prev_price) if prev_price < lo else (prev_price - hi)
    contradiction = distance / price
    return Check(
        "drift_corroboration", False,
        f"prior {prev_price:.2f} ({elapsed_h:.1f}h ago) is {contradiction * 100:.2f}% outside "
        f"the path implied by a {reported * 100:+.2f}% 24h change "
        f"[{lo:.2f}, {hi:.2f}] - one of the two prints is wrong",
        contradiction,
    )
