"""Decision outcome grading — what happened AFTER the call.

Every approved decision is graded once it matures (default +24h) against
live spot: LONG wins when spot rises, SHORT when it falls, NEUTRAL scores 0
(held out, correctly or not — abstention is scored, not ignored).
Results append to config/outcomes.jsonl (one JSON object per line, the
verifiable forward record) and are stamped back onto the desk feed entry.

This is the loop the project was missing: decisions were logged but never
graded, so the system could neither learn nor demonstrate learning.
Backtest says what SHOULD work (docs/BACKTEST.md); this says what DID.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def grade_decision(entry_price: float, later_price: float, direction: str) -> float | None:
    """Outcome in bps. None when ungradeable (bad inputs or NEUTRAL)."""
    if not entry_price or not later_price or entry_price <= 0 or later_price <= 0:
        return None
    move_bps = (later_price - entry_price) / entry_price * 10000.0
    if direction == "LONG":
        return round(move_bps, 1)
    if direction == "SHORT":
        return round(-move_bps, 1)
    return None


def outcomes_path() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "config" / "outcomes.jsonl"


def record_outcome(entry: dict[str, Any]) -> None:
    """Append one graded decision. Best-effort — never break the cycle."""
    try:
        with open(outcomes_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def read_outcomes(limit: int = 50) -> list[dict[str, Any]]:
    """Tail of the forward record (newest last in file)."""
    try:
        lines = outcomes_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in records if isinstance(r.get("outcome_bps"), (int, float))]
    if not scored:
        return {"graded": 0, "avg_bps": None, "wins": 0, "losses": 0,
                "note": "accumulating — decisions grade +24h after approval"}
    wins = sum(1 for r in scored if r["outcome_bps"] > 0)
    return {
        "graded": len(scored),
        "avg_bps": round(sum(r["outcome_bps"] for r in scored) / len(scored), 1),
        "wins": wins,
        "losses": len(scored) - wins,
        "note": "forward record, graded against live spot",
    }


def grade_matured(decisions: list[dict], market_data: dict,
                  horizon_s: float, now: float | None = None) -> list[dict]:
    """Grade entries older than horizon_s using current cycle spot.

    Mutates entries in place (stamps outcome_bps/graded_at), appends each
    graded entry to outcomes.jsonl, returns the newly graded list.
    """
    now = now if now is not None else time.time()
    graded = []
    for d in decisions:
        if "outcome_bps" in d:
            continue
        if now - float(d.get("time", now)) < horizon_s:
            continue
        spot_now = (market_data.get(d.get("asset"), {}) or {}).get("spot_price")
        outcome = grade_decision(float(d.get("entry_price") or 0),
                                 float(spot_now or 0), str(d.get("signal") or ""))
        d["outcome_bps"] = outcome
        d["graded_at"] = now
        if outcome is not None:
            record_outcome({**d, "graded_at": now})
            graded.append(d)
    return graded
