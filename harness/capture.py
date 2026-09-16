"""
Entry point for the scheduled capture. Runs every signal's detector, logs
every record, prints a one-line summary per instrument.

    python -m harness.capture
"""

from __future__ import annotations

import sys
import time

from . import store
from .signals import basis, meta, perps

SIGNALS = [basis, perps, meta]

STATUS_MARK = {
    "tradeable": "***",
    "fired": "***",
    "market_summary": " . ",
    "not_fillable": " ~ ",
    "clean_no_trade": "   ",
    "rejected": " ! ",
    "no_reference": " ? ",
    "error": " x ",
}


def main() -> int:
    started = time.time()
    all_records: list[dict] = []

    for module in SIGNALS:
        try:
            records = module.detect()
        except Exception as exc:  # a broken signal must not kill the capture
            print(f"[{module.SIGNAL}] detector failed: {exc}", file=sys.stderr)
            continue
        all_records.extend(records)

    store.append_many(store.CANDIDATES, all_records)

    tradeable = 0
    for r in all_records:
        status = r.get("status", "error")
        if status == "tradeable":
            tradeable += 1
        mark = STATUS_MARK.get(status, "   ")
        basis_bps = r.get("gross_basis_bps")
        shown = f"{basis_bps:+5d}bps" if basis_bps is not None else "    --   "
        label = r.get('ticker') or r.get('coin') or r.get('venue') or '-'
        print(f"{mark} {label:<6} {shown}  {status:<15} {r.get('reason', '')}")

    print(
        f"\n{len(all_records)} records, {tradeable} tradeable, "
        f"{time.time() - started:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
