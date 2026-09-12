"""
Data sources. Every function here returns raw observations with provenance
attached - never a blended "price". Blending is verify.py's job, and it only
blends things that agree.

Hard rule learned the expensive way: never use DexScreener's /latest/dex/search
endpoint for pricing. It returned $317 for AAPLx while the per-token endpoint
said $334 and the token's own 24h change proved $334 was right.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from . import config

DEXSCREENER = "https://api.dexscreener.com"
COINGECKO = "https://api.coingecko.com/api/v3"
JUPITER = "https://lite-api.jup.ag"
HYPERLIQUID = "https://api.hyperliquid.xyz/info"
FINNHUB = "https://finnhub.io/api/v1"
POLYGON = "https://api.polygon.io"

USER_AGENT = "basis-harness/0.1"


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def _request(method: str, url: str, **kwargs) -> Any:
    headers = kwargs.pop("headers", {}) or {}
    headers.setdefault("User-Agent", USER_AGENT)
    last_error = None
    for attempt in range(3):
        try:
            r = requests.request(method, url, timeout=20, headers=headers, **kwargs)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                last_error = "rate limited"
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"{method} {url} failed: {last_error}")


def get(url: str, **kwargs) -> Any:
    return _request("GET", url, **kwargs)


def post(url: str, **kwargs) -> Any:
    return _request("POST", url, **kwargs)


# --------------------------------------------------------------------------
# on-chain spot: per-pool reads
# --------------------------------------------------------------------------

@dataclass
class Pool:
    dex: str
    label: str
    quote_symbol: str
    price_usd: float
    liquidity_usd: float
    volume_24h: float
    change_24h: float | None
    pair_address: str

    @property
    def is_stable_quoted(self) -> bool:
        return self.quote_symbol in config.STABLES

    @property
    def qualifies(self) -> bool:
        return (
            self.is_stable_quoted
            and self.liquidity_usd >= config.MIN_POOL_LIQUIDITY_USD
            and self.price_usd > 0
        )


@dataclass
class PoolSnapshot:
    mint: str
    chain: str
    pools: list[Pool] = field(default_factory=list)
    fetched_at: int = 0

    @property
    def qualifying(self) -> list[Pool]:
        return [p for p in self.pools if p.qualifies]


def pools_for(chain: str, mint: str) -> PoolSnapshot:
    """Per-token pool list. The only endpoint we trust for pricing."""
    raw = get(f"{DEXSCREENER}/token-pairs/v1/{chain}/{mint}") or []
    pools = []
    for p in raw:
        base = (p.get("baseToken") or {}).get("address", "")
        if base.lower() != mint.lower():
            continue
        try:
            pools.append(Pool(
                dex=p.get("dexId", "?"),
                label=",".join(p.get("labels") or []),
                quote_symbol=(p.get("quoteToken") or {}).get("symbol", "?"),
                price_usd=float(p.get("priceUsd") or 0),
                liquidity_usd=float((p.get("liquidity") or {}).get("usd") or 0),
                volume_24h=float((p.get("volume") or {}).get("h24") or 0),
                change_24h=(p.get("priceChange") or {}).get("h24"),
                pair_address=p.get("pairAddress", ""),
            ))
        except (TypeError, ValueError):
            continue
    pools.sort(key=lambda x: x.liquidity_usd, reverse=True)
    return PoolSnapshot(mint=mint, chain=chain, pools=pools, fetched_at=int(time.time()))


def coingecko_prices(platform: str, mints: list[str]) -> dict[str, float]:
    """Second opinion. Deliberately a different provider, not a different endpoint."""
    headers = {"x-cg-demo-api-key": config.KEYS.coingecko} if config.KEYS.coingecko else {}
    data = get(
        f"{COINGECKO}/simple/token_price/{platform}",
        params={"contract_addresses": ",".join(mints), "vs_currencies": "usd"},
        headers=headers,
    ) or {}
    return {k.lower(): v["usd"] for k, v in data.items() if isinstance(v, dict) and "usd" in v}


# --------------------------------------------------------------------------
# executable price: what a router would actually fill
# --------------------------------------------------------------------------

@dataclass
class Quote:
    size_usd: float
    effective_price: float
    price_impact_pct: float
    route_count: int

    def as_dict(self) -> dict:
        return {
            "size_usd": self.size_usd,
            "effective_price": round(self.effective_price, 6),
            "price_impact_pct": round(self.price_impact_pct, 6),
            "route_count": self.route_count,
        }


def jupiter_buy_quote(mint: str, decimals: int, size_usd: float) -> Quote | None:
    """
    What it costs to actually buy `size_usd` of the token, slippage included.
    This is the number that decides whether a gap is real, because an
    aggregator mid is not a fill.
    """
    amount = int(size_usd * 1_000_000)  # USDC has 6 decimals
    data = get(
        f"{JUPITER}/swap/v1/quote",
        params={
            "inputMint": config.USDC_SOLANA,
            "outputMint": mint,
            "amount": amount,
            "slippageBps": 50,
            "restrictIntermediateTokens": "true",
        },
    )
    if not data or "outAmount" not in data:
        return None

    out_tokens = int(data["outAmount"]) / (10 ** decimals)
    if out_tokens <= 0:
        return None

    return Quote(
        size_usd=size_usd,
        effective_price=size_usd / out_tokens,
        price_impact_pct=float(data.get("priceImpactPct") or 0),
        route_count=len(data.get("routePlan") or []),
    )


def jupiter_token_decimals(mint: str) -> int | None:
    data = get(f"{JUPITER}/tokens/v2/search", params={"query": mint})
    if isinstance(data, list):
        for token in data:
            if token.get("id", "").lower() == mint.lower():
                return token.get("decimals")
    return None


# --------------------------------------------------------------------------
# perp leg
# --------------------------------------------------------------------------

def hyperliquid_mids() -> dict[str, float]:
    """
    All mid prices keyed by coin. HIP-3 builder markets are namespaced
    (e.g. "trade:AAPL"); run `python -m harness.probe perps` once to see the
    exact keys on the venue before trusting config.Instrument.perp.
    """
    data = post(HYPERLIQUID, json={"type": "allMids"}) or {}
    out = {}
    for coin, mid in data.items():
        try:
            out[coin] = float(mid)
        except (TypeError, ValueError):
            continue
    return out


def hyperliquid_perp_meta() -> list[dict]:
    data = post(HYPERLIQUID, json={"type": "meta"}) or {}
    return data.get("universe", [])


# --------------------------------------------------------------------------
# equity reference
# --------------------------------------------------------------------------

@dataclass
class EquityQuote:
    ticker: str
    price: float
    previous_close: float | None
    source: str
    quote_ts: int | None

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_close": self.previous_close,
            "source": self.source,
            "quote_ts": self.quote_ts,
        }


def equity_quote(ticker: str) -> EquityQuote | None:
    """Finnhub first, Polygon as fallback. Both keyed; neither is free for commercial use."""
    if config.KEYS.finnhub:
        q = get(f"{FINNHUB}/quote", params={"symbol": ticker, "token": config.KEYS.finnhub})
        if q and q.get("c"):
            return EquityQuote(ticker, float(q["c"]), q.get("pc"), "finnhub", q.get("t"))

    if config.KEYS.polygon:
        q = get(
            f"{POLYGON}/v2/aggs/ticker/{ticker}/prev",
            params={"adjusted": "true", "apiKey": config.KEYS.polygon},
        )
        results = (q or {}).get("results") or []
        if results:
            bar = results[0]
            return EquityQuote(ticker, float(bar["c"]), None, "polygon_prev_close", bar.get("t"))

    return None
