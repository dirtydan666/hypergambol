"""
Configuration: the universe, the cost model, and the thresholds that decide
whether a candidate is worth logging as tradeable.

Everything tunable lives here so the signal modules stay about logic.
"""

import os
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Instruments
# --------------------------------------------------------------------------

USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


@dataclass(frozen=True)
class Instrument:
    ticker: str            # underlying equity symbol, e.g. "AAPL"
    name: str
    chain: str             # dexscreener chainId: solana | robinhood | base
    mint: str              # token mint / contract address
    decimals: int = 8      # verify with `python -m harness.probe tokens`
    perp: str | None = None  # Hyperliquid coin key; confirm with `probe perps`


# Mints verified against DexScreener, Sept 2026.
UNIVERSE: list[Instrument] = [
    Instrument("AAPL", "Apple",       "solana", "XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp", perp="xyz:AAPL"),
    Instrument("NVDA", "NVIDIA",      "solana", "Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh", perp="xyz:NVDA"),
    Instrument("SPY",  "S&P 500 ETF", "solana", "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W", perp=None),
    Instrument("TSLA", "Tesla",       "solana", "XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB", perp="xyz:TSLA"),
    Instrument("HOOD", "Robinhood",   "solana", "XsvNBAYkrDRNhA7wPHQfX3ZUXZyZLdnCQDfHZ56bzpg", perp="xyz:HOOD"),
    Instrument("GME",  "GameStop",    "solana", "Xsf9mBktVB9BSU5kf4nHxPq5hCBJ2j2ui3ecFGxPRGc", perp="xyz:GME"),
]

STABLES = {"USDC", "USDT", "USDG", "USDY", "DAI", "syrupUSDC"}


# --------------------------------------------------------------------------
# Verification thresholds
#
# These exist because of four false positives in the first two captures:
# Apple 5%, Robinhood 8%, GameStop 7%, Tesla 4% - every one of them a data
# artifact that looked exactly like money.
# --------------------------------------------------------------------------

# Pools holding less than this are decoration, not a price.
MIN_POOL_LIQUIDITY_USD = 50_000

# Need at least this many qualifying pools before a print is believable.
MIN_POOLS_FOR_CONSENSUS = 2

# Max spread across qualifying pools before we call the token unpriceable.
MAX_POOL_DISPERSION = 0.005          # 0.5%

# Max disagreement between two independent providers.
MAX_PROVIDER_DISAGREEMENT = 0.005    # 0.5%

# The Apple check: if a price implies a move the token's own 24h change does
# not corroborate, the price is wrong. Allow this much unexplained daily drift.
MAX_UNEXPLAINED_24H_DRIFT = 0.02     # 2 percentage points


# --------------------------------------------------------------------------
# Cost model - what it actually takes to get in and out
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CostModel:
    perp_taker_fee: float = 0.0009   # Hyperliquid HIP-3, per side
    perp_sides: int = 2              # enter + exit
    solana_overhead: float = 0.001   # priority fees, failed-tx buffer, round trip
    # Spot slippage is NOT estimated here - it comes from a live router quote.

    @property
    def fixed_round_trip(self) -> float:
        return self.perp_taker_fee * self.perp_sides + self.solana_overhead


COSTS = CostModel()

# A candidate must beat costs by this much to be logged as tradeable.
# Anything thinner is noise dressed as an opportunity.
EDGE_MARGIN = 0.005                  # 0.5 percentage points over cost

# Clip size the executable quote is tested at. The honest question is not
# "is there a gap" but "is there a gap at a size worth trading".
QUOTE_SIZES_USD = [1_000, 2_500, 5_000]


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

# How long after detection we grade a basis candidate.
BASIS_HORIZONS_HOURS = [4, 24, 72]


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

@dataclass
class Keys:
    finnhub: str = field(default_factory=lambda: os.environ.get("FINNHUB_KEY", ""))
    polygon: str = field(default_factory=lambda: os.environ.get("POLYGON_KEY", ""))
    coingecko: str = field(default_factory=lambda: os.environ.get("COINGECKO_KEY", ""))
    helius: str = field(default_factory=lambda: os.environ.get("HELIUS_KEY", ""))


KEYS = Keys()

DATA_DIR = os.environ.get("HARNESS_DATA_DIR", "data")
