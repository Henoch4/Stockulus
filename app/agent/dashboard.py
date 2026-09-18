"""
Dashboard / metrics endpoint for pattern registry, curator, risk gate, and execution.
Exposes JSON endpoints for hackathon demo / judge dashboard.
Mainnet: disable or restrict to internal IPs.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .curator import CuratorAgent
from .execution.risk_gate import RiskGate
from .multi_leg import MultiLegExecutionManager
from .audit_logger_sol import SolanaAuditLogger

if TYPE_CHECKING:
    from .agent import AutonomousTradingAgent


class Dashboard:
    """
    Aggregates metrics from all subsystems for external dashboard / judge review.
    """

    def __init__(
        self,
        agent: AutonomousTradingAgent,
        curator: CuratorAgent,
        risk_gate: Any,
        multi_leg_manager: MultiLegExecutionManager,
        onchain_logger: SolanaAuditLogger | None = None,
    ):
        self.agent = agent
        self.curator = curator
        self.risk_gate = risk_gate
        self.multi_leg = multi_leg_manager
        self.onchain_logger = onchain_logger

    def get_all_metrics(self) -> dict:
        """Full metrics dump for dashboard."""
        return {
            "timestamp": time.time(),
            "agent": self._agent_metrics(),
            "curator": self.curator.get_dashboard_data(),
            "risk_gate": self._risk_gate_metrics(),
            "multi_leg": self._multi_leg_metrics(),
            "patterns": self.agent.pattern_registry.get_metrics(),
            "onchain": self._onchain_metrics(),
            "supporters": self.get_supporters(),
        }

    def _agent_metrics(self) -> dict:
        return {
            "agent_id": self.agent.agent_id,
            "dry_run": self.agent.dry_run,
            "max_position_usd": self.agent.max_position_usd,
            "current_regime": self.agent._current_regime,
            "active_patterns": self.agent.pattern_registry.get_active_patterns(),
            "total_cycles": getattr(self.agent, "_cycle_count", 0),
        }

    def _risk_gate_metrics(self) -> dict:
        return {
            "kill_switch": self.risk_gate.kill_switch_status(),
            "daily_stats": self.risk_gate.get_daily_stats("default"),
            "regime_status": {
                asset: self.risk_gate.regime_status(asset)
                for asset in self.risk_gate.allowed_assets
            },
            "limits": {
                "max_position_usd": self.risk_gate.max_position_usd,
                "max_daily_loss_usd": self.risk_gate.max_daily_loss_usd,
                "max_daily_trades": self.risk_gate.max_daily_trades,
                "max_slippage_pct": self.risk_gate.max_slippage_pct,
                "min_confidence_bps": self.risk_gate.min_confidence_bps,
            },
        }

    def _multi_leg_metrics(self) -> dict:
        if not self.multi_leg:
            return {"available": False, "note": "agent uses direct meteora swap"}
        return {
            "open_packages": self.multi_leg.open_package_count(),
            "max_concurrent": self.multi_leg.max_concurrent_packages,
            "active_instruments": list(self.multi_leg._active_instruments),
        }

    def _onchain_metrics(self) -> dict:
        if not self.onchain_logger:
            return {"connected": False}
        return {
            "connected": self.onchain_logger.is_connected(),
            "agent_address": str(self.onchain_logger.agent_address),
            "program_id": str(self.onchain_logger.program_id),
        }

    def get_supporters(self) -> dict:
        """Supporters wall - launch contributors, updated by hand per donation.

        Source: config/supporters.json ({"supporters": [{name, amount_sol, tx}]}).
        Zero dependencies, no chain calls; amounts verifiable against tx hashes.
        """
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent.parent / "config" / "supporters.json"
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
            supporters = data.get("supporters", [])
        except (OSError, ValueError):
            supporters = []
        return {
            "count": len(supporters),
            "total_sol": round(sum(float(s.get("amount_sol", 0)) for s in supporters), 4),
            "supporters": supporters,
        }

    def get_fee_pipeline(self) -> dict:
        """STCKLS fee pipeline — earned vs bought-back, updated per live execution.

        Source: config/fee_ledger.json ({"buyback_wallet": str|None,
        "entries": [{ts, kind, amount_usd, tx, note}]}).
        kinds: "carry_earn" (swap/strategy fees), "creator_fee" (Clawpump/pump
        creator cut claimed), "buyback" (STCKLS bought back).
        Zero dependencies, no chain calls; amounts verifiable against tx hashes.
        """
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent.parent / "config" / "fee_ledger.json"
        try:
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data.get("entries", [])
            buyback_wallet = data.get("buyback_wallet")
        except (OSError, ValueError):
            entries, buyback_wallet = [], None
        earned = sum(
            float(e.get("amount_usd", 0))
            for e in entries
            if e.get("kind") in ("carry_earn", "creator_fee")
        )
        bought = sum(
            float(e.get("amount_usd", 0)) for e in entries if e.get("kind") == "buyback"
        )
        return {
            "buyback_wallet": buyback_wallet,
            "earned_usd": round(earned, 4),
            "bought_back_usd": round(bought, 4),
            "coverage": round(bought / earned, 4) if earned > 0 else 0.0,
            "entries": entries,
        }

    # ─── Convenience endpoints for specific views ───

    def get_pattern_summary(self) -> dict:
        """Compact pattern view for judge dashboard."""
        metrics = self.agent.pattern_registry.get_metrics()
        return {
            "active_count": len([m for m in metrics.values() if m["enabled"]]),
            "total_patterns": len(metrics),
            "patterns": {
                name: {
                    "enabled": m["enabled"],
                    "signals": m["signals_generated"],
                    "trades": m["trades_executed"],
                    "pnl": m["pnl_usd"],
                    "win_rate": m["win_rate"],
                } for name, m in metrics.items()
            },
        }

    def get_curator_summary(self) -> dict:
        """Curator state for judge dashboard."""
        data = self.curator.get_dashboard_data()
        return {
            "profile": data["current_profile"],
            "config": data["profile_config"],
            "last_regime": data["last_regime"],
            "trailing_pnl": data["trailing_pnl"],
            "trades_since_switch": data["trades_since_switch"],
            "forced_defensive": data["forced_defensive"],
            "recent_switches": len(data["switch_history"]),
        }

    def get_risk_summary(self) -> dict:
        """Risk gate status for judge dashboard."""
        ks = self.risk_gate.kill_switch_status()
        ds = self.risk_gate.get_daily_stats("default")
        return {
            "kill_switch": ks["active"],
            "ks_reason": ks["reason"],
            "daily_loss": ds["loss"],
            "daily_loss_limit": ds["loss_limit"],
            "daily_trades": ds["trade_count"],
            "daily_trades_limit": ds["trade_count_limit"],
            "regime_scales": {
                asset: self.risk_gate.regime_scale(asset)
                for asset in self.risk_gate.allowed_assets
            },
        }

    def get_execution_summary(self) -> dict:
        """Execution/multi-leg status for judge dashboard."""
        return {
            "open_packages": self.multi_leg.open_package_count(),
            "active_instruments": list(self.multi_leg._active_instruments),
            "max_concurrent": self.multi_leg.max_concurrent_packages,
        }


# ─── FastAPI/HTTP endpoint helper (optional) ───

def create_dashboard_routes(app, dashboard: Dashboard):
    """
    Add dashboard routes to a FastAPI app.
    Usage:
        from fastapi import FastAPI
        app = FastAPI()
        create_dashboard_routes(app, dashboard)
    """
    try:
        from fastapi import FastAPI
    except ImportError:
        return  # FastAPI not installed, skip

    @app.get("/metrics/all")
    async def all_metrics():
        return dashboard.get_all_metrics()

    @app.get("/metrics/patterns")
    async def pattern_metrics():
        return dashboard.get_pattern_summary()

    @app.get("/metrics/curator")
    async def curator_metrics():
        return dashboard.get_curator_summary()

    @app.get("/metrics/risk")
    async def risk_metrics():
        return dashboard.get_risk_summary()

    @app.get("/metrics/execution")
    async def execution_metrics():
        return dashboard.get_execution_summary()

    @app.get("/metrics/fees")
    async def fee_metrics():
        return dashboard.get_fee_pipeline()

    @app.get("/metrics/supporters")
    async def supporter_metrics():
        return dashboard.get_supporters()

    @app.get("/health")
    async def health():
        return {"status": "ok", "timestamp": time.time()}


# ─── CLI demo ───

async def demo():
    """Print all metrics to stdout for quick inspection."""
    import json
    print(json.dumps({
        "patterns": "see agent.pattern_registry.get_metrics()",
        "curator": "see curator.get_dashboard_data()",
        "risk": "see risk_gate.get_daily_stats()",
    }, indent=2))


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo())