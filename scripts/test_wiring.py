import asyncio, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agent import AutonomousTradingAgent, PatternMetrics
from app.agent.execution.risk_gate import RiskGate, DurableDailyCounters
from app.agent.meteora_executor import MeteoraExecutor
from app.agent.data_integrity import DataIntegrityGate


class FakeXStocks:
    BASE = "x"

    async def get_price(self, asset):
        return {"price": 180.0}

    async def get_multiplier(self, asset):
        return {"current": 1.0}

    async def close(self):
        pass


async def main():
    counters = DurableDailyCounters(path=os.path.join(os.path.dirname(__file__), "_test_risk.json"), enabled=True)
    rg = RiskGate(
        max_position_usd=100, max_daily_loss_usd=20, max_daily_trades=10,
        max_leverage=1.0, min_confidence_bps=7000,
        allowed_assets=["xAAPL", "xTSLA", "xNVDA"],
        counters_durable=True, counter_store=counters,
    )
    me = MeteoraExecutor("https://api.devnet.solana.com")
    ag = AutonomousTradingAgent(
        xstocks_client=FakeXStocks(), meteora_executor=me,
        risk_gate=rg, dry_run=True, max_position_usd=100,
        agent_id="t", integrity_gate=DataIntegrityGate(30.0),
        regime_window=50,
    )
    print("agent instantiated OK")
    print("active patterns:", ag.pattern_registry.get_active_patterns())

    result = await ag.run_trading_cycle(["xAAPL", "xTSLA", "xNVDA"])
    print("status:", result.status)
    print("signals:", len(result.signals))
    print("decisions:", len(result.decisions))
    print("executions:", len(result.executions))
    print("errors:", result.errors)
    print("regime:", result.regime)
    print("pattern_metrics keys:", list(result.pattern_metrics.keys()))


asyncio.run(main())