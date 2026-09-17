"""demo_live_micro.py — T13 evidence run (devnet, capped, fully on-chain).

One trading cycle, fully live except sizing:
  xStocks spot (live) → carry signal → RiskGate ($5 cap) →
  TradeAuditTrail.log_decision (real tx) → DBC swap (real tx, ~$5) →
  TradeAuditTrail.record_execution (real tx)

Costs: ~$5 wSOL + 3 audit tx fees (devnet dust). Uses the AGENT wallet.
Run:  C:\\Python314\\python.exe scripts\\demo_live_micro.py
Requires .env: RPC_URL, ANCHOR_PROGRAM_ID, AGENT_KEYPAIR_PATH, DBC_POOL_AAPLX.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

from solders.keypair import Keypair

from app.agent import AutonomousTradingAgent
from app.agent.execution.risk_gate import RiskGate, DurableDailyCounters
from app.agent.xstocks import XStocksClient
from app.agent.meteora_executor import MeteoraExecutor
from app.agent.audit_logger_sol import SolanaAuditLogger
from app.agent.curator import CuratorAgent
from app.agent.data_integrity import DataIntegrityGate

MAX_POSITION_USD = 5.0
MAX_DAILY_LOSS_USD = 20.0
ASSETS = ["AAPLx"]


def load_keypair(path: str) -> Keypair:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    try:
        secret = bytes(json.loads(raw))
    except ValueError:
        secret = bytes.fromhex(raw)
    return Keypair.from_bytes(secret)


async def main() -> int:
    rpc_url = os.getenv("RPC_URL", "https://api.devnet.solana.com")
    keypair_path = os.getenv("AGENT_KEYPAIR_PATH", "./agent_keypair.json")
    audit_program_id = os.getenv("ANCHOR_PROGRAM_ID", "")
    if not audit_program_id or audit_program_id.startswith("1111"):
        print("ERROR: ANCHOR_PROGRAM_ID placeholder — deploy first (H1).")
        return 1
    if not os.path.exists(keypair_path):
        print(f"ERROR: keypair missing at {keypair_path} (H2).")
        return 1

    kp = load_keypair(keypair_path)
    print(f"agent: {kp.pubkey()}  cap: ${MAX_POSITION_USD}  assets: {ASSETS}", flush=True)

    # Allowlist = symbols + configured DBC pools: orders route to pool pubkeys,
    # so pools must be explicitly authorized (exact match, no guessing).
    pools = [
        os.getenv("DBC_POOL_AAPLX", ""),
        os.getenv("DBC_POOL_TSLAX", ""),
        os.getenv("DBC_POOL_NVDAX", ""),
    ]
    allowed = ["AAPLx", "TSLAx", "NVDAx"] + [p for p in pools if p and not p.startswith("PLACEHOLDER")]
    risk_gate = RiskGate(
        max_position_usd=MAX_POSITION_USD,
        max_daily_loss_usd=MAX_DAILY_LOSS_USD,
        max_daily_trades=10,
        max_leverage=1.0,
        min_confidence_bps=6000,
        allowed_assets=allowed,
        counters_durable=False,
    )

    xstocks = XStocksClient()
    meteora = MeteoraExecutor(rpc_url, keypair_path=keypair_path)
    audit = SolanaAuditLogger(rpc_url, audit_program_id, kp)
    await audit.connect()
    print("audit logger connected", flush=True)

    # One-time PDA + risk params for this demo cap (tightening-safe).
    try:
        tx = await audit.initialize()
        print(f"agent state init tx: {tx}", flush=True)
    except Exception as e:
        print(f"agent state init note (already initialized?): {str(e)[:200]}", flush=True)
    try:
        tx = await audit.set_risk_params(MAX_POSITION_USD, MAX_DAILY_LOSS_USD, 10000, 6000)
        print(f"risk params tx: {tx}", flush=True)
    except Exception as e:
        print(f"risk params note: {str(e)[:200]}", flush=True)

    agent = AutonomousTradingAgent(
        xstocks_client=xstocks,
        meteora_executor=meteora,
        risk_gate=risk_gate,
        onchain_logger=audit,
        dry_run=False,
        max_position_usd=MAX_POSITION_USD,
        agent_id="stockulus-demo-001",
        integrity_gate=DataIntegrityGate(staleness_threshold_s=30.0),
        audit_log=None,
        regime_window=50,
    )

    result = await agent.run_trading_cycle(ASSETS)
    print(f"status: {result.status}  regime: {result.regime}", flush=True)
    print(f"signals: {len(result.signals)}  decisions: {len(result.decisions)}  "
          f"executions: {len(result.executions)}", flush=True)
    for d in result.decisions:
        print("decision:", json.dumps(d), flush=True)
    for e in result.executions:
        print("execution:", json.dumps(e), flush=True)
    for err in result.errors:
        print("error:", err, flush=True)

    await audit.close()
    await xstocks.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
