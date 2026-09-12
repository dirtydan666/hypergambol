import sys, time
sys.path.insert(0, "/home/claude/signal-harness")
from harness.sources import Pool, PoolSnapshot
from harness.verify import verify_price

def mk(price, liq, change, quote="USDC"):
    return Pool(dex="raydium", label="CLMM", quote_symbol=quote, price_usd=price,
                liquidity_usd=liq, volume_24h=1e6, change_24h=change, pair_address="x")

def snap(pools): return PoolSnapshot(mint="M", chain="solana", pools=pools, fetched_at=int(time.time()))
def prior(price, hours): return {"price": price, "age_seconds": hours * 3600}

# THE case: 20h ago we recorded 317.36. Now pools say 334 and report -0.5% on the day.
# Those two observations cannot both be right.
apple_now = snap([mk(333.87, 248_654, -0.74), mk(333.95, 335_359, -0.66), mk(334.20, 83_284, -0.44)])
r = verify_price(apple_now, provider_price=334.20, previous=prior(317.36, 20))
print("apple vs bad prior -> ok:", r.ok, "| failed:", r.failed_checks)
print("   ", [c.detail for c in r.checks if c.name == "drift_corroboration"][0])

# Same capture, but the prior observation was sane.
r2 = verify_price(apple_now, provider_price=334.20, previous=prior(333.10, 20))
print("apple vs good prior -> ok:", r2.ok, "| price:", round(r2.price, 2))

# First ever capture: check arms later, does not block.
r3 = verify_price(apple_now, provider_price=334.20, previous=None)
print("first capture -> ok:", r3.ok)

# Provider disagreement (Tesla).
tsla = snap([mk(350.31, 2_001_651, 0.33), mk(349.92, 486_552, 0.31), mk(350.18, 108_418, 0.38)])
r4 = verify_price(tsla, provider_price=364.66, previous=prior(350.0, 6))
print("tesla -> ok:", r4.ok, "| failed:", r4.failed_checks)

# Thin single pool (GME).
r5 = verify_price(snap([mk(19.83, 20_000, -1.0)]), provider_price=21.14)
print("thin gme -> ok:", r5.ok, "| failed:", r5.failed_checks)

# Pools disagreeing with each other.
r6 = verify_price(snap([mk(100.0, 100_000, 0.1), mk(107.0, 100_000, 0.1)]), provider_price=103.0,
                  previous=prior(103.0, 5))
print("split pools -> ok:", r6.ok, "| failed:", r6.failed_checks)

# A genuine overnight move must NOT be flagged: token really did fall 6%, and the
# prior observation is consistent with that path.
real_move = snap([mk(94.0, 200_000, -6.0), mk(94.1, 150_000, -6.1)])
r7 = verify_price(real_move, provider_price=94.05, previous=prior(99.8, 20))
print("real -6% move -> ok:", r7.ok, "| failed:", r7.failed_checks)

assert not r.ok and "drift_corroboration" in r.failed_checks, "guard missed the Apple case"
assert r2.ok and r3.ok
assert not r4.ok and "provider_agreement" in r4.failed_checks
assert not r5.ok and "depth" in r5.failed_checks
assert not r6.ok and "pool_dispersion" in r6.failed_checks
assert r7.ok, "guard rejected a genuine move"
print("\nALL GUARD TESTS PASS")
