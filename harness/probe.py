"""
One-off checks to run before trusting config.

    python -m harness.probe perps     # exact Hyperliquid coin keys for equity perps
    python -m harness.probe tokens    # real decimals for every mint in the universe
    python -m harness.probe pools     # per-pool prices for one capture, unfiltered

Run `perps` and `tokens` first. Two config values are guesses until it does:
the HIP-3 perp naming (builder markets may be namespaced) and token decimals.
"""

from __future__ import annotations

import sys

from . import config
from .sources import hyperliquid_mids, hyperliquid_perp_meta, jupiter_token_decimals, pools_for


def perps() -> None:
    meta = hyperliquid_perp_meta()
    mids = hyperliquid_mids()
    wanted = {i.ticker for i in config.UNIVERSE}

    print(f"{len(meta)} perp markets listed\n")
    print("Possible matches for the universe:")
    for coin in sorted(mids):
        bare = coin.split(":")[-1].upper()
        if bare in wanted:
            print(f"  {coin:<24} mid {mids[coin]}")

    print("\nIf a ticker is missing above, it is not listed or is namespaced "
          "differently - grep the full list:")
    for m in meta[:40]:
        print(f"  {m.get('name')}")
    if len(meta) > 40:
        print(f"  ... {len(meta) - 40} more")


def tokens() -> None:
    for inst in config.UNIVERSE:
        actual = jupiter_token_decimals(inst.mint)
        flag = "" if actual == inst.decimals else f"  <-- config says {inst.decimals}"
        print(f"  {inst.ticker:<5} {inst.mint}  decimals={actual}{flag}")


def pools() -> None:
    for inst in config.UNIVERSE:
        snap = pools_for(inst.chain, inst.mint)
        print(f"\n{inst.ticker} ({len(snap.pools)} pools, {len(snap.qualifying)} qualifying)")
        for p in snap.pools[:8]:
            mark = "*" if p.qualifies else " "
            change = f"{p.change_24h:+.2f}%" if p.change_24h is not None else "   n/a"
            print(f" {mark} {p.dex:<10} /{p.quote_symbol:<8} {p.price_usd:>10.4f}  "
                  f"liq ${p.liquidity_usd:>12,.0f}  24h {change}")


COMMANDS = {"perps": perps, "tokens": tokens, "pools": pools}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    COMMANDS[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
