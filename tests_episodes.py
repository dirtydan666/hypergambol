"""
Tests for episode de-duplication.

Written before the code is trusted, the same way the Apple case was written
before the drift check was trusted. Each test is a real pathology from the
first scorecard, not an invented one.

    python tests_episodes.py
"""

from harness import episodes

HOUR = 3600
T0 = 1_757_000_000


def rec(signal, who, status, hour, kind=""):
    key = "coin" if signal in ("perps", "meta") else "ticker"
    return {"signal": signal, key: who, "status": status,
            "kind": kind, "detected_at": T0 + int(hour * HOUR)}


def check(name, got, want):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}: got {got!r}, want {want!r}")
    return ok


results = []

# 1. The actual bug. A condition that stays true across many captures is ONE
#    call, not one per capture. NVDA was logged 518 times in three days.
nvda = [rec("perps", "NVDA", "fired", h * 0.25, "crowded_long") for h in range(518)]
starts = episodes.episode_starts(nvda)
results.append(check("persistent condition collapses to one episode", len(starts), 1))

# 2. A gap longer than the window means the condition lapsed and came back.
#    That is a second, separate call - it was re-entered on fresh information.
lapsed = [rec("perps", "AVAX", "fired", 0, "crowded_long"),
          rec("perps", "AVAX", "fired", 3, "crowded_long")]
results.append(check("3h gap starts a new episode", len(episodes.episode_starts(lapsed)), 2))

# 3. A gap inside the window is the same episode still running.
continued = [rec("perps", "AVAX", "fired", 0, "crowded_long"),
             rec("perps", "AVAX", "fired", 1.5, "crowded_long")]
results.append(check("1.5h gap is a continuation", len(episodes.episode_starts(continued)), 1))

# 4. Flipping side is a NEW claim, not a continuation - even 15 minutes later.
#    Status alone would have missed this; that is why the signature includes kind.
flip = [rec("perps", "SOL", "fired", 0, "crowded_long"),
        rec("perps", "SOL", "fired", 0.25, "crowded_short")]
results.append(check("long -> short is a new episode", len(episodes.episode_starts(flip)), 2))

# 5. Changing verdict on the same subject is a new claim.
verdict = [rec("basis", "AAPL", "clean_no_trade", 0),
           rec("basis", "AAPL", "tradeable", 0.25)]
results.append(check("no-trade -> tradeable is a new episode", len(episodes.episode_starts(verdict)), 2))

# 6. Two subjects never share an episode, however close in time.
pair = [rec("perps", "NVDA", "fired", 0, "crowded_long"),
        rec("perps", "AVAX", "fired", 0, "crowded_long")]
results.append(check("subjects are independent", len(episodes.episode_starts(pair)), 2))

# 7. Signals are independent even for the same ticker. basis:AAPL is not perps:AAPL.
cross = [rec("basis", "AAPL", "clean_no_trade", 0),
         rec("perps", "AAPL", "fired", 0, "crowded_long")]
results.append(check("same ticker, different signal", len(episodes.episode_starts(cross)), 2))

# 8. Non-claim records are never episodes. market_summary asserts nothing about
#    the future, so it must not enter the numerator or the denominator.
noise = [rec("meta", "-", "market_summary", h * 0.25) for h in range(20)]
results.append(check("market_summary is never graded", len(episodes.episode_starts(noise)), 0))
results.append(check("rejected is never graded",
                     len(episodes.episode_starts([rec("basis", "TSLA", "rejected", 0)])), 0))

# 9. Claim type. act and abstain are different assertions and must be labelled
#    so the scoreboard can keep them apart. This is fix #2's foundation.
labelled = episodes.annotate([rec("basis", "AAPL", "clean_no_trade", 0),
                              rec("basis", "NVDA", "tradeable", 0),
                              rec("basis", "TSLA", "not_fillable", 0),
                              rec("perps", "SOL", "fired", 0, "crowded_long")])
results.append(check("claims labelled",
                     [r["claim"] for r in labelled],
                     ["abstain", "act", "abstain", "act"]))

# 10. Unsorted input must not change the answer. The log is append-only but the
#     scorer reads it whole, and a mis-ordered read would invent episodes.
shuffled = [nvda[5], nvda[0], nvda[3], nvda[1]]
results.append(check("order-independent", len(episodes.episode_starts(shuffled)), 1))

# 11. The headline number. Three days of captures across the real subject mix
#     should collapse by roughly two orders of magnitude.
mixed = nvda + [rec("perps", "AVAX", "fired", h * 0.25, "crowded_long") for h in range(331)]
summary = episodes.summarise(mixed)
results.append(check("summary counts claimable", summary["claimable_records"], 849))
results.append(check("summary counts episodes", summary["episodes"], 2))
results.append(check("summary counts subjects", summary["distinct_subjects"], 2))
results.append(check("repetition factor", summary["repetition_factor"], 424.5))

print()
print(f"{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
