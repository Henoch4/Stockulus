"""Serve the Stockulus desk (web/) + live /metrics/* endpoints.

Read-only: builds the same agent stack as __main__ but never sends
transactions and never runs trading cycles. Metrics reflect local risk
counters, fee ledger, supporters wall, and on-chain connection state.

Usage (repo root):
    python -m app.agent.serve
    # → http://127.0.0.1:8000/  (desk), /metrics/all (JSON)
"""
import asyncio
import json
import os
from dotenv import load_dotenv
from pathlib import Path

# Explicit .env path (repo root): bare load_dotenv() relies on CWD search,
# which silently misses on some Windows setups → config loads empty.
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent.parent / ".env")

from app.agent import AutonomousTradingAgent
from app.agent.execution.risk_gate import RiskGate, DurableDailyCounters
from app.agent.xstocks import XStocksClient
from app.agent.meteora_executor import MeteoraExecutor
from app.agent.audit_logger_sol import SolanaAuditLogger
from app.agent.curator import CuratorAgent
from app.agent.data_integrity import DataIntegrityGate
from app.agent.multi_leg import MultiLegExecutionManager
from app.agent.dashboard import Dashboard, create_dashboard_routes
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


async def build_dashboard() -> Dashboard:
    keypair_path = os.getenv("AGENT_KEYPAIR_PATH", "./agent_keypair.json")
    kp = load_keypair(keypair_path)

    risk_state_path = os.getenv("RISK_STATE_PATH", "./risk_state.json")
    counters = DurableDailyCounters(path=risk_state_path, enabled=True)
    risk_gate = RiskGate(
        max_position_usd=100,
        max_daily_loss_usd=20,
        max_daily_trades=10,
        max_leverage=1.0,
        min_confidence_bps=7000,
        allowed_assets=["AAPLx", "TSLAx", "NVDAx"],
        counters_durable=True,
        counter_store=counters,
    )

    xstocks = XStocksClient()
    rpc_url = os.getenv("RPC_URL", "https://api.devnet.solana.com")
    meteora = MeteoraExecutor(rpc_url, keypair_path=keypair_path)

    audit_program_id = os.getenv("ANCHOR_PROGRAM_ID")
    if not audit_program_id:
        raise RuntimeError("ANCHOR_PROGRAM_ID not set in .env")
    audit = SolanaAuditLogger(rpc_url, audit_program_id, kp)
    await audit.connect()

    curator = CuratorAgent(audit_log=None)
    integrity = DataIntegrityGate(staleness_threshold_s=30.0)
    multi_leg = MultiLegExecutionManager()

    dry_run = os.getenv("DRY_RUN", "true").strip().lower() != "false"

    agent = AutonomousTradingAgent(
        xstocks_client=xstocks,
        meteora_executor=meteora,
        risk_gate=risk_gate,
        onchain_logger=audit,
        dry_run=dry_run,
        max_position_usd=100,
        agent_id="stockulus-demo",
        integrity_gate=integrity,
        audit_log=None,
        regime_window=50,
    )
    return Dashboard(
        agent=agent,
        curator=curator,
        risk_gate=risk_gate,
        multi_leg_manager=multi_leg,
        onchain_logger=audit,
    )


def create_app() -> "FastAPI":
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    dashboard: Dashboard = asyncio.run(build_dashboard())
    app = FastAPI(title="Stockulus desk")
    create_dashboard_routes(app, dashboard)

    web_dir = Path(__file__).resolve().parent.parent.parent / "web"
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="desk")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("SERVE_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)
