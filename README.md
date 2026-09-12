# Signal harness

Measures candidate trading signals and publishes their hit rate. Nothing in
here is called a setup until it has a track record.

The pipeline is the same for every signal:

```
detect  ->  verify  ->  log  ->  score at horizon  ->  publish hit rate
```

Signal 01 is tokenized-equity basis. Smart-money wallets and launchpad rotation
plug into the identical contract: a module with `detect()` and
`score(candidate, horizon)`.

## Why the verifier came first

Two manual captures produced four multi-percent "opportunities" — Apple 5%,
Robinhood 8%, GameStop 7%, Tesla 4%. Every one was a data artifact. The Apple
one passed a two-source cross-check because both providers were wrong together
at the same moment.

So `verify.py` runs four checks on every price, and the one that would have
caught Apple is the fourth: **a price is a claim about where a token moved, and
the token's own 24h change is an independent claim about the same thing — when
they contradict each other, the price is wrong.**

| Check | Kills |
|---|---|
| `depth` | prices from one thin pool |
| `pool_dispersion` | pools that disagree with each other |
| `provider_agreement` | one aggregator out on its own |
| `drift_corroboration` | prints the token's own 24h change contradicts |

Rejected candidates are logged, not dropped. The rejection log is the most
credible artifact this repo produces.

## Setup

```bash
pip install -r requirements.txt

# Confirm the two config values that are currently guesses
python -m harness.probe perps      # exact Hyperliquid coin keys
python -m harness.probe tokens     # real token decimals

python -m harness.capture          # one capture
python -m harness.report           # scorecard
```

Repo secrets for the scheduled run: `FINNHUB_KEY` (or `POLYGON_KEY`), and
optionally `COINGECKO_KEY`.

### Before the first real capture

Two values in `config.py` are assumptions until `probe` confirms them:

1. **Perp coin keys.** HIP-3 builder markets may be namespaced (`trade:AAPL`
   rather than `AAPL`). `probe perps` prints what the venue actually exposes.
2. **Token decimals.** Defaulted to 8. Wrong decimals silently corrupt every
   executable quote, which is the one number the whole system turns on.

## What gets logged

Every instrument, every capture, with a status:

| Status | Meaning |
|---|---|
| `tradeable` | cleared verification, cleared the cost floor, **and** survived a live router quote |
| `not_fillable` | gap looked real on mid price, died on an executable quote |
| `clean_no_trade` | verified price, gap under the cost floor — the normal result |
| `rejected` | failed verification, with the specific check named |
| `no_reference` | no perp mid and no equity quote available |

The fixed cost floor is `perp taker 0.09% × 2 + Solana overhead 0.1% + 0.5%
margin` = **78bps**, and a gap has to clear that before the harness will spend
a router call on it. The spot leg's real cost is never estimated — it comes back
in the quote itself at $1k, $2.5k and $5k, and gets subtracted there. Together
they land around the 1% round trip that killed every gap seen so far. The honest
question was never whether a gap exists, but whether it exists at a size worth
trading.

## Scoring

Basis candidates are graded at 4h, 24h and 72h: did the gap converge, and would
a delta-neutral entry have paid after costs? `clean_no_trade` rows are graded
too — a signal that fires on nothing and one that fires on noise look identical
until the misses are scored as well.

## Data

Append-only JSONL in `data/`, committed by the scheduled job. Every record
carries a git timestamp that cannot be backdated, including the losers. A track
record is only worth something if the bad entries are still in it.

## Roadmap

- **Signal 02 — smart money.** Wallet PnL on Solana and Robinhood Chain; what
  consistently-profitable wallets are accumulating. Needs Helius-grade history.
  PnL attribution is noisy (bridges, airdrops, transfers) so it gets its own
  verification checks before anything is published.
- **Signal 03 — launchpad rotation.** Launch flow by pairing asset and venue:
  what is being launched, which quote assets are getting force-bought, where fee
  revenue is moving.
- **Execution.** Only if the scorecard earns it. Deterministic and fast, with
  pre-committed rules — no model in the hot path.

## Not advice

Market data and the arithmetic behind it. A spread on a screen is not a
position until the fees, the slippage and the funding are paid.
