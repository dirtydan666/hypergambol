"""
Append-only JSONL storage.

Append-only is the point. Committed back to the repo by the scheduled job,
every candidate carries a git timestamp nobody can backdate - including the
ones that got rejected and the ones that got scored as wrong. A track record
is only worth something if the losing entries are still in it.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

from . import config

CANDIDATES = "candidates.jsonl"
OUTCOMES = "outcomes.jsonl"
OBSERVATIONS = "observations.jsonl"


def _path(name: str) -> str:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    return os.path.join(config.DATA_DIR, name)


def append(name: str, record: dict) -> None:
    with open(_path(name), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def append_many(name: str, records: list[dict]) -> None:
    if not records:
        return
    with open(_path(name), "a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def read(name: str) -> Iterator[dict]:
    path = _path(name)
    if not os.path.exists(path):
        return iter(())

    def _iter():
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    return _iter()


def scored_ids() -> set[str]:
    return {f"{o['candidate_id']}@{o['horizon_hours']}" for o in read(OUTCOMES)}


def last_verified(mint: str) -> dict | None:
    """
    Most recent capture for this mint that produced a price we would have
    published. Feeds the drift check: our own history is the one source that
    cannot be wrong in the same way the aggregators are.
    """
    found = None
    for record in read(CANDIDATES):
        if record.get("mint") != mint:
            continue
        verification = record.get("verification") or {}
        if verification.get("price") is None or not verification.get("ok"):
            continue
        found = {"price": verification["price"], "ts": record.get("detected_at")}
    return found
