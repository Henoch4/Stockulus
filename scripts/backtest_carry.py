"""Carry-economics backtest: 60d in-sample / 30d out-of-sample, costs modeled.

Substrate (documented limits, see docs/BACKTEST.md):
- Underlying daily closes + dividend events (Yahoo public chart API).
- NO token history exists publicly (xStocks live-only, DBC pools days old),
  so this tests CARRY ECONOMICS (div + lending - fees), not basis timing.
  Token-leg reality enters as execution overlay: live venue spread + the two
  real DBC fee schedules, charged on every rebalance flip.
- Borrow/lending proxy BORROW_BPS (locate data is Phase-C paid data).
- Long/flat only (no spot short in backtest); hedged claim strips price
  drift: daily PnL = carry/365 on invested days.

Usage (repo root):  python scripts/backtest_carry.py [--borrow-bps 100] [--cost-bps 150]
Prints JSON summary + verdict block.
"""
import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.yahoo import YahooClient, UNDERLYING
from app.agent.stock_carry import carry_annualized

IS_DAYS = 60
OOS_DAYS = 30
MIN_CARRY_BPS = 50.0


def ttm_yield(bars, divs, i):
    t_end = bars[i]["t"]
    t_start = t_end - 365 * 86400
    paid = sum(d["amount"] for d in divs if t_start < d["t"] <= t_end)
    px = bars[i]["close"]
    return paid / px if px > 0 else 0.0


def run_window(bars, divs, borrow, cost_bps, min_carry_bps=MIN_CARRY_BPS):
    """Daily long/flat carry sim. Returns dict of metrics."""
    rets, flips, invested, pos = [], 0, 0, 0
    wins = 0
    peak, max_dd, cum = 1.0, 0.0, 1.0
    for i in range(1, len(bars)):
        y = ttm_yield(bars, divs, i - 1)
        carry = carry_annualized(y, borrow, 0.0, 0.0)
        want = 1 if carry * 10000 >= min_carry_bps else 0
        if want != pos:
            flips += 1
            cum *= 1 - cost_bps / 10000.0
        pos = want
        day = carry / 365.0 * pos
        rets.append(day)
        if pos:
            invested += 1
            if day > 0:
                wins += 1
        cum *= 1 + day
        peak = max(peak, cum)
        max_dd = max(max_dd, (peak - cum) / peak)
    n = len(rets)
    mean = sum(rets) / n if n else 0.0
    var = sum((r - mean) ** 2 for r in rets) / n if n else 0.0
    sd = math.sqrt(var)
    sharpe = (mean / sd * math.sqrt(365)) if sd > 0 else 0.0
    return {
        "days": n, "invested_days": invested, "flips": flips,
        "total_bps": round((cum - 1) * 10000, 1),
        # Sharpe is degenerate by construction here (price drift stripped,
        # near-constant daily carry -> ~zero variance). Reported raw, but the
        # verdict judges on total_bps and max_dd, not Sharpe.
        "sharpe_raw": round(sharpe, 2),
        "max_dd_bps": round(max_dd * 10000, 1),
        "day_win_rate": round(wins / invested, 3) if invested else None,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--borrow-bps", type=float, default=100.0)
    ap.add_argument("--cost-bps", type=float, default=150.0)
    args = ap.parse_args()
    borrow = args.borrow_bps / 10000.0

    yc = YahooClient()
    out: dict = {"params": {"borrow_bps": args.borrow_bps, "cost_bps": args.cost_bps,
                            "is_days": IS_DAYS, "oos_days": OOS_DAYS,
                            "min_carry_bps": MIN_CARRY_BPS},
                 "assets": {}}
    try:
        for asset in UNDERLYING:
            data = await yc.daily(asset, "1y")
            bars = data["bars"]
            divs = data["dividends"]
            if len(bars) < IS_DAYS + OOS_DAYS + 5:
                out["assets"][asset] = {"error": f"only {len(bars)} bars"}
                continue
            oos = bars[-(OOS_DAYS + 1):]
            istart = len(bars) - (OOS_DAYS + 1) - (IS_DAYS + 1)
            ist = bars[max(0, istart):len(bars) - (OOS_DAYS + 1)]
            out["assets"][asset] = {
                "underlying": data["underlying"],
                "bars": len(bars),
                "is": run_window(ist, divs, borrow, args.cost_bps),
                "oos": run_window(oos, divs, borrow, args.cost_bps),
            }
    finally:
        await yc.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
