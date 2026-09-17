import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

from app.agent import AutonomousTradingAgent
from app.agent.execution.risk_gate import RiskGate, DurableDailyCounters
from app.agent.xstocks import XStocksClient
from app.agent.meteora_executor import MeteoraExecutor
from app.agent.audit_logger_sol import SolanaAuditLogger
from app.agent.curator import CuratorAgent
from app.agent.data_integrity import DataIntegrityGate
from solders.keypair import Keypair


def load_keypair(path: str) -> Keypair:
    """Load a solana-keygen JSON (array of 64 ints) or a hex seed file."""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    try:
        secret = bytes(json.loads(raw))
    except (ValueError, json.JSONDecodeError):
        secret = bytes.fromhex(raw)
    if len(secret) not in (32, 64):
        raise ValueError(f"keypair file must be 32 or 64 bytes, got {len(secret)}")
    return Keypair.from_bytes(secret)

async def main():
    # Load keypair
    keypair_path = os.getenv("AGENT_KEYPAIR_PATH", "./agent_keypair.json")
    kp = load_keypair(keypair_path)

    # Risk gate (durable)
    risk_state_path = os.getenv("RISK_STATE_PATH", "./risk_state.json")
    counters = DurableDailyCounters(path=risk_state_path, enabled=True)
    risk_gate = RiskGate(
        max_position_usd=100,
        max_daily_loss_usd=20,
        max_daily_trades=10,
        max_leverage=1.0,
        min_confidence_bps=7000,
        allowed_assets=["xAAPL", "xTSLA", "xNVDA"],
        counters_durable=True,
        counter_store=counters,
    )

    # Clients
    xstocks = XStocksClient()
    rpc_url = os.getenv("RPC_URL", "https://api.devnet.solana.com")
    keypair_path = os.getenv("AGENT_KEYPAIR_PATH", "./agent_keypair.json")
    meteora = MeteoraExecutor(rpc_url, keypair_path=keypair_path)

    audit_program_id = os.getenv("ANCHOR_PROGRAM_ID")
    if not audit_program_id:
        print("ERROR: ANCHOR_PROGRAM_ID not set in .env")
        return

    audit = SolanaAuditLogger(rpc_url, audit_program_id, kp)
    await audit.connect()
    await audit.set_risk_params(100, 20, 10000, 7000)

    curator = CuratorAgent(audit_log=None)
    integrity = DataIntegrityGate(staleness_threshold_s=30.0)

    # DRY_RUN defaults to true: live swaps only on explicit DRY_RUN=false.
    # (Placeholder perp/borrow/div data must never reach a real pool.)
    dry_run = os.getenv("DRY_RUN", "true").strip().lower() != "false"

    agent = AutonomousTradingAgent(
        xstocks_client=xstocks,
        meteora_executor=meteora,
        risk_gate=risk_gate,
        onchain_logger=audit,
        dry_run=dry_run,
        max_position_usd=100,
        agent_id="delta-zero-demo",
        integrity_gate=integrity,
        audit_log=None,
        regime_window=50,
    )

    # Run 3 cycles
    for i in range(3):
        print(f"\n=== Cycle {i+1} ===")
        result = await agent.run_trading_cycle(["xAAPL", "xTSLA", "xNVDA"])
        print(f"Signals: {len(result.signals)}, Decisions: {len(result.decisions)}, Executions: {len(result.executions)}")
        if result.errors:
            print(f"Errors: {result.errors}")
        print(f"Patterns: {result.pattern_metrics}")
        await asyncio.sleep(10)

    await audit.close()
    await xstocks.close()

if __name__ == "__main__":
    asyncio.run(main())