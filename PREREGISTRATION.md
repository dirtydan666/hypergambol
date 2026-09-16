# Pre-registration: the perps continuation hypothesis

**Registered:** 2026-09-16T19:00:00Z (unix `1789585200`)
**Status:** open, not tradeable
**Git is the proof.** This file was committed before the registration timestamp.
Every episode counted toward this test is detected after it. Both facts are
checkable by anyone: `git log --format=%cI -- PREREGISTRATION.md` against the
`detected_at` field of every record in `data/candidates.jsonl`.

---

## Why this file exists

The harness ran for three days and produced a striking result, and striking
results found by looking at data you already have are usually wrong. This is the
mechanism that stops that from happening quietly: state the claim, state what
would kill it, timestamp both, and then do not touch either.

If the hypothesis is right, this file is what makes it believable. If it is
wrong, this file is what makes the failure impossible to hide.

## What was observed (in-sample — excluded from the test)

Signal 02 fires when perp funding is crowded, predicting that the crowded side
unwinds and price **reverses**. Over 2026-09-13 to 2026-09-16, graded by episode:

| Horizon | Episodes | Reversal correct | Mean, reversal direction |
|---:|---:|---:|---:|
| 4h | 224 | 42.9% | −17bps |
| 24h | 163 | 47.9% | −67bps |
| 72h | 44 | **20.5%** | **−241bps** |

At 72h the signal is not merely useless, it is reliably wrong: 9 correct out of
44, which a fair coin produces about once in nineteen thousand tries. Nine cells
were examined (three signals × three horizons); after a Bonferroni correction
for that, the result survives at p ≈ 5×10⁻⁴.

**None of these 44 episodes count toward the test below.** They are what
generated the idea and cannot also be its evidence.

## The hypothesis

> Crowded perp funding predicts price **continuation** in the crowded direction
> at a 72-hour horizon, not reversal.

There is a plausible mechanism, which is the only reason this is worth testing
rather than dismissing as a fluke: funding stays crowded *because the trend
persists*. Traders pay to hold the winning side. Crowding may therefore be a
symptom of momentum rather than of exhaustion.

## The test, fixed in advance

**Primary horizon: 72h.** Only 72h. The in-sample effect was specific to it, and
testing all three horizons and reporting whichever wins is how noise gets
published. 4h and 24h will be reported for completeness and are not the test.

**Sample required before any verdict: 100 episodes at 72h.** At the observed
rate that is roughly a week.

**Cost assumption: 30bps round trip** — taker both sides plus slippage. Fixed
now so it cannot be revised downward later to rescue a marginal result.

**Confirmed** — all three must hold:
1. Continuation hit rate > 55%
2. Mean return in the continuation direction > +30bps net of costs
3. The 95% confidence interval on the hit rate excludes 50%

**Falsified** — either is enough:
1. Continuation hit rate ≤ 50%
2. Mean return in the continuation direction ≤ 0 net of costs

**Inconclusive:** anything in between, or fewer than 100 episodes after 30 days.
Inconclusive is a real outcome and will be published as one.

## What is not being claimed

This is not a trading signal. It is a hypothesis generated from three days of a
single market regime, and the correct response to it is to wait, not to trade.
Nothing here is advice, and the author of this file holds no position in it.

## How it gets graded

`harness/signals/perps.py` records both verdicts on every episode: the original
reversal claim and the inverted continuation claim. Detection is unchanged, so
both are graded on exactly the same events and neither gets a favourable
selection of them. `harness/report.py` counts the continuation claim only where
`detected_at >= 1789585200`.

The original reversal claim keeps being graded too. It is losing, and deleting a
losing record is the one thing that would make everything else here worthless.
