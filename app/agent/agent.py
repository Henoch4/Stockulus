"""
Autonomous multi-pattern trading agent for tokenized stocks.

Architecture: Pattern Registry → Curator → Risk Gate → Multi-Leg Execution → On-Chain Audit
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from .signals import (
    Signal,
    generate_signals,
    mean_reversion_signal,
    momentum_signal,
    funding_rate_signal,
    stock_carry_signal,
    ensemble_signal,
)
from .execution import (
    OrderExecutor,
    OrderRequest,
    OrderResult,
    OrderStatus,
    RiskGate,
    RiskCheckResult,
    ExecutionError,
)
from .audit_logger_sol import SolanaAuditLogger
from .xstocks import XStocksClient
from .meteora_executor import MeteoraExecutor
from .curator import CuratorAgent
from .data_integrity import DataIntegrityGate, IntegrityResult
from .audit_trail import AuditLog
from .regime_hmm import infer_regime_simple, dbc_action_for_regime
from .stock_carry import tokenized_stock_carry_signal, vault_9010_allocation
from .dashboard import Dashboard

logger = logging.getLogger(__name__)


# ─── Pattern Registry ───

@dataclass
class PatternMetrics:
    """Runtime metrics for a single pattern."""
    name: str
    enabled: bool = False
    signals_generated: int = 0
    trades_executed: int = 0
    pnl_usd: float = 0.0
    win_rate: float = 0.0
    last_signal_ts: float = 0.0
    config: dict = field(default_factory=dict)


class PatternRegistry:
    """
    Registry of all available trading patterns.
    Curator activates/deactivates patterns based on regime.
    """

    def __init__(self):
        self.patterns: dict[str, PatternMetrics] = {}
        self._register_default_patterns()

    def _register_default_patterns(self):
        """Register all available patterns with default configs."""
        self.patterns = {
            "carry_bsm": PatternMetrics(
                name="carry_bsm",
                config={"min_basis_bps": 5.0, "min_carry_bps": 50.0},
            ),
            "regime_hmm": PatternMetrics(
                name="regime_hmm",
                config={"features": ["vol", "funding_z", "basis", "ret"]},
            ),
            "validation_gate": PatternMetrics(
                name="validation_gate",
                config={"calmar_bar": 1.0, "pbo_threshold": 0.5},
            ),
            "structured_9010": PatternMetrics(
                name="structured_9010",
                config={"safe_pct": 0.9, "opt_pct": 0.1},
            ),
            "dbc_vol_tune": PatternMetrics(
                name="dbc_vol_tune",
                config={"regime_map": {0: "linear", 1: "exp", 2: "exp"}},
            ),
        }

    def get_active_patterns(self) -> list[str]:
        return [name for name, m in self.patterns.items() if m.enabled]

    def activate(self, name: str, config: dict | None = None):
        if name in self.patterns:
            self.patterns[name].enabled = True
            if config:
                self.patterns[name].config.update(config)
            logger.info(f"Pattern activated: {name}")

    def deactivate(self, name: str):
        if name in self.patterns:
            self.patterns[name].enabled = False
            logger.info(f"Pattern deactivated: {name}")

    def set_active_set(self, names: list[str]):
        """Activate only the given patterns; deactivate all others."""
        for name in self.patterns:
            self.patterns[name].enabled = name in names
        logger.info(f"Active pattern set: {self.get_active_patterns()}")

    def record_signal(self, pattern_name: str):
        if pattern_name in self.patterns:
            self.patterns[pattern_name].signals_generated += 1
            self.patterns[pattern_name].last_signal_ts = time.time()

    def record_trade(self, pattern_name: str, pnl: float):
        if pattern_name in self.patterns:
            m = self.patterns[pattern_name]
            m.trades_executed += 1
            m.pnl_usd += pnl
            if m.trades_executed > 0:
                m.win_rate = sum(1 for _ in range(m.trades_executed) if pnl > 0) / m.trades_executed

    def get_metrics(self) -> dict:
        return {name: {
            "enabled": m.enabled,
            "signals_generated": m.signals_generated,
            "trades_executed": m.trades_executed,
            "pnl_usd": round(m.pnl_usd, 2),
            "win_rate": round(m.win_rate, 4),
            "last_signal_ts": m.last_signal_ts,
            "config": m.config,
        } for name, m in self.patterns.items()}


# ─── Curator Profile ↔ Pattern Map ───

CURATOR_PROFILE_PATTERNS = {
    "conservative": ["carry_bsm", "validation_gate"],
    "standard": ["carry_bsm", "regime_hmm", "dbc_vol_tune"],
    "aggressive": ["carry_bsm", "regime_hmm", "dbc_vol_tune", "structured_9010"],
    "defensive": ["validation_gate"],  # no new trades, only unwinds
}


# ─── DBC pool resolution (env; H4 fills real pubkeys post create_pool) ───

import os as _os


def _dbc_pool_for_asset(asset: str) -> str:
    """Map xSTOCK symbol → DBC pool pubkey from env (DBC_POOL_AAPLX/...).

    Returns a placeholder when unset — downstream swap fails closed (no pool,
    no trade) instead of routing to a wrong pool. Never guess a pubkey.
    """
    sym = asset.upper()
    # "AAPLx" → DBC_POOL_AAPLX first, DBC_POOL_AAPL fallback.
    pool = _os.getenv(f"DBC_POOL_{sym}") or _os.getenv(f"DBC_POOL_{sym.rstrip('X')}", "")
    if not pool or pool == "PLACEHOLDER_POOL_PUBKEY":
        return f"{asset}-DBC"
    return pool


# ─── Fee ledger (STCKLS value loop; best-effort, file-backed) ───

def _record_ledger_fee(kind: str, amount_usd: float, tx: str, note: str = "") -> None:
    """Append one entry to config/fee_ledger.json. Never raises."""
    try:
        import json as _json
        import time as _time
        from pathlib import Path as _Path

        path = _Path(__file__).resolve().parent.parent.parent / "config" / "fee_ledger.json"
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"buyback_wallet": None, "entries": []}
        entries = data.setdefault("entries", [])
        entries.append({
            "ts": _time.time(),
            "kind": kind,
            "amount_usd": round(float(amount_usd), 6),
            "tx": tx,
            "note": note,
        })
        path.write_text(_json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("fee ledger write skipped", exc_info=True)


# ─── Trading Cycle Result ───

@dataclass
class TradingCycleResult:
    cycle_id: str
    timestamp: float
    signals: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    executions: list[dict] = field(default_factory=list)
    total_pnl_usd: float = 0.0
    total_fees_usd: float = 0.0
    status: str = "completed"
    errors: list[str] = field(default_factory=list)
    curator: dict | None = None
    pattern_metrics: dict = field(default_factory=dict)
    regime: int | None = None


# ─── Autonomous Trading Agent ───

class AutonomousTradingAgent:
    """
    Multi-pattern autonomous trading agent for tokenized stocks.

    Flow per cycle:
    1. Fetch market data (xStocks spot, DBC perp, funding, borrow)
    2. Run integrity gate (staleness, corporate actions)
    3. Infer regime (HMM) → curator selects profile → pattern subset
    4. Generate signals from ACTIVE patterns only
    5. Ensemble + risk gate + on-chain audit log
    6. Multi-leg execution via Meteora DBC
    7. Record metrics per pattern
    """

    def __init__(
        self,
        xstocks_client: XStocksClient,
        meteora_executor: MeteoraExecutor,
        risk_gate: RiskGate,
        onchain_logger: SolanaAuditLogger | None = None,
        dry_run: bool = True,
        max_position_usd: float = 100,
        agent_id: str = "delta-zero-agent-001",
        sizing_mode: str = "kelly",
        kelly_fraction: float = 0.5,
        integrity_gate: DataIntegrityGate | None = None,
        audit_log: AuditLog | None = None,
        expected_equity: float | None = None,
        regime_window: int = 50,
    ):
        self.xstocks = xstocks_client
        self.meteora = meteora_executor
        self.risk_gate = risk_gate
        self.onchain_logger = onchain_logger
        self.dry_run = dry_run
        self.max_position_usd = max_position_usd
        self.agent_id = agent_id
        self.sizing_mode = sizing_mode
        self.kelly_fraction = kelly_fraction
        self.regime_window = regime_window

        self.integrity_gate = integrity_gate
        self.audit_log = audit_log
        self.expected_equity = expected_equity

        # Pattern system
        self.pattern_registry = PatternRegistry()
        self.curator = CuratorAgent(audit_log=audit_log)

        # Execution (risk-gated swaps handled in run_trading_cycle via self.meteora)

        # State
        self._last_cycle_equity: float | None = None
        self._risk_lock = asyncio.Lock()
        self._audit_lock = asyncio.Lock()
        self._current_regime: int = 0

        # Dashboard
        self.dashboard = Dashboard(
            agent=self,
            curator=self.curator,
            risk_gate=self.risk_gate,
            multi_leg_manager=None,  # agent uses direct meteora swap, not multi_leg_manager
            onchain_logger=self.onchain_logger,
        )

        # Initialize patterns for default profile
        self._sync_patterns_from_curator()

    def _sync_patterns_from_curator(self):
        """Sync active patterns from curator's current profile."""
        profile = self.curator.active_profile()
        profile_name = self.curator.state.current_profile
        active_patterns = CURATOR_PROFILE_PATTERNS.get(profile_name, ["carry_bsm"])
        self.pattern_registry.set_active_set(active_patterns)
        logger.info(f"Curator profile '{profile_name}' → active patterns: {active_patterns}")

    async def _fetch_market_data(self, asset: str) -> dict:
        """Fetch xStocks spot, DBC perp, funding, borrow rate."""
        spot_data = await self.xstocks.get_price(asset)
        spot_price = float(spot_data.get("price", 0))
        mult_data = await self.xstocks.get_multiplier(asset)
        multiplier = float(mult_data.get("current", 1.0))
        spot_display = spot_price * multiplier

        # DBC perp price from Meteora pool (simplified: use spot + basis)
        perp_price = spot_display * 1.001  # placeholder

        # Borrow rate from lending protocol (placeholder)
        borrow_rate = 0.05  # 5% APY

        # Dividend yield from multiplier history
        div_yield = 0.015  # 1.5% placeholder

        # Funding rate (perp)
        funding_rate = 0.0001

        return {
            "asset": asset,
            "spot_price": spot_display,
            "perp_price": perp_price,
            "borrow_rate": borrow_rate,
            "div_yield": div_yield,
            "funding_rate": funding_rate,
            "timestamp": time.time(),
        }

    def _infer_regime(self, market_data: dict) -> int:
        """Infer regime from aggregated market data."""
        # Aggregate features across assets
        vols = []
        funding_zs = []
        bases = []
        rets = []

        for asset, data in market_data.items():
            spot = data.get("spot_price", 0)
            perp = data.get("perp_price", 0)
            funding = data.get("funding_rate", 0)
            if spot > 0:
                basis_bps = (perp - spot) / spot * 10000
                bases.append(basis_bps)
            funding_zs.append(funding * 10000)  # simplified
            vols.append(0.3)  # placeholder
            rets.append(0.0)

        avg_vol = sum(vols) / len(vols) if vols else 0.3
        avg_funding_z = sum(funding_zs) / len(funding_zs) if funding_zs else 0
        avg_basis = sum(bases) / len(bases) if bases else 0
        avg_ret = sum(rets) / len(rets) if rets else 0

        return infer_regime_simple(avg_vol, avg_funding_z, avg_basis, avg_ret)

    async def _generate_pattern_signals(self, asset: str, market_data: dict) -> list[Signal]:
        """Generate signals ONLY from active patterns."""
        active = self.pattern_registry.get_active_patterns()
        if not active:
            return []

        md = market_data[asset]
        spot = md["spot_price"]
        perp = md["perp_price"]
        funding = md["funding_rate"]
        borrow = md["borrow_rate"]
        div = md["div_yield"]

        signals = []

        # Pattern: carry_bsm (Merton delta-neutral carry)
        if "carry_bsm" in active:
            sig = tokenized_stock_carry_signal(
                asset, spot, perp, md["borrow_rate"], md["div_yield"],
                md["funding_rate"], fee_drag=0.001
            )
            signals.append(sig)
            self.pattern_registry.record_signal("carry_bsm")

        # Pattern: regime_hmm (already handled via curator/DBC config)
        # No direct signal, but influences curator + DBC

        # Pattern: validation_gate (no signal, gates all patterns)
        # Handled in validation.py

        # Pattern: structured_9010 (allocation, not a signal)
        # Handled in vault allocation

        # Pattern: dbc_vol_tune (DBC config, not a signal)
        # Handled in meteora_executor

        return signals

    async def _process_asset(self, asset: str, market_data: dict, cycle_id: str) -> dict:
        out = {"signals": [], "decisions": [], "executions": [], "errors": []}

        # Integrity check
        if self.integrity_gate:
            tick = type('obj', (object,), {"timestamp": market_data[asset]["timestamp"], "funding_rate": market_data[asset]["funding_rate"]})
            integrity = self.integrity_gate.check_market_data({asset: tick}, time.time())
            if integrity.blocks_trading:
                out["errors"].append(f"Integrity blocked {asset}: {integrity.reasons}")
                return out

        # Generate signals from active patterns
        signals = await self._generate_pattern_signals(asset, market_data)
        if not signals:
            return out

        ensemble_sig = ensemble_signal(asset, signals)
        if not ensemble_sig.is_tradeable:
            return out

        out["signals"].append({
            "asset": asset,
            "ensemble": ensemble_sig.to_dict(),
            "individual": [s.to_dict() for s in signals],
        })

        # Risk gate
        order = self._signal_to_order(ensemble_sig, market_data[asset])
        if not order:
            return out

        risk_result = self.risk_gate.check_order(
            order, self.agent_id,
            current_price=market_data[asset]["spot_price"],
            current_price_timestamp=market_data[asset]["timestamp"],
        )
        if not risk_result.approved:
            out["errors"].append(f"Risk gate rejected: {risk_result.reason}")
            return out

        # On-chain audit log
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        payload = {
            "decision_id": decision_id,
            # Single-leg (non-package) decision: None hashes to bytes32(0) on-chain.
            "package_id": None,
            "asset": asset,
            "signal": ensemble_sig.direction,
            "strategy": ensemble_sig.strategy,
            "confidence_bps": ensemble_sig.confidence_bps,
            "entry_price": ensemble_sig.entry_price or 0,
            "size_usd": float(order.size),
            "risk_hash": self.risk_gate.compute_risk_hash(),
        }

        if self.onchain_logger:
            try:
                await self.onchain_logger.log_decision(**payload)
            except Exception as e:
                out["errors"].append(f"On-chain log failed: {e}")
                return out

        out["decisions"].append({
            "decision_id": decision_id,
            "asset": asset,
            "signal": ensemble_sig.direction,
            "confidence_bps": ensemble_sig.confidence_bps,
            "size_usd": float(order.size),
        })

        # Execute via Meteora DBC (skip in dry_run)
        if not self.dry_run:
            try:
                # order.size is USD notional; DBC swap takes QUOTE-token units.
                # Convert via SOL price (env SOL_PRICE_USD; Pyth feed is Phase C).
                sol_price = float(_os.getenv("SOL_PRICE_USD", "150.0") or 150.0)
                amount_quote = float(order.size) / sol_price if sol_price > 0 else 0.0
                swap_result = self.meteora.swap(
                    pool=order.inst_id,  # DBC pool pubkey
                    amount_in=amount_quote,
                    min_out=amount_quote * 0.99,
                    swap_base_for_quote=(order.side == "sell"),
                )
                exec_result = {
                    "decision_id": decision_id,
                    "asset": asset,
                    "tx": swap_result.tx,
                    "out_amount": swap_result.out_amount,
                    "price_impact": swap_result.price_impact,
                    "fee": swap_result.fee,
                    "status": "filled",
                }
                out["executions"].append(exec_result)

                # Fee pipeline: ledger the reported fee (estimated until swap
                # log-parsing lands). Best-effort — never break the cycle.
                _record_ledger_fee(
                    kind="carry_earn",
                    amount_usd=float(swap_result.fee or 0.0),
                    tx=swap_result.tx,
                    note=f"{asset} DBC swap fee (reported, estimated)",
                )

                # Record pattern PnL
                for sig in signals:
                    self.pattern_registry.record_trade(sig.strategy, 0.0)  # PnL computed later

                if self.onchain_logger:
                    await self.onchain_logger.record_execution(
                        decision_id=decision_id,
                        fill_price=market_data[asset]["spot_price"],
                        fill_size_usd=float(order.size),
                        fee_usd=swap_result.fee,
                        success=True,
                    )
            except Exception as e:
                out["errors"].append(f"Execution failed: {e}")
        else:
            # Dry run: mock execution result
            exec_result = {
                "decision_id": decision_id,
                "asset": asset,
                "tx": f"dryrun_{uuid.uuid4().hex[:8]}",
                "out_amount": float(order.size),
                "price_impact": 0.0,
                "fee": 0.0,
                "status": "filled (dry_run)",
            }
            out["executions"].append(exec_result)
            for sig in signals:
                self.pattern_registry.record_trade(sig.strategy, 0.0)

        return out

    def _signal_to_order(self, sig: Signal, market_data: dict) -> OrderRequest | None:
        if not sig.is_tradeable:
            return None
        side = "buy" if sig.direction == "LONG" else "sell"
        size_usd = self.max_position_usd * (sig.confidence_bps / 10000.0)
        return OrderRequest(
            # Live: DBC pool pubkey from env (DBC_POOL_AAPLX/...). Unset =
            # placeholder that fails closed downstream (no pool → no swap).
            inst_id=_dbc_pool_for_asset(sig.asset),
            side=side,
            order_type="market",
            size=f"{size_usd:.2f}",
            confidence_bps=sig.confidence_bps,
            intended_price=sig.entry_price,
        )

    async def run_trading_cycle(self, assets: list[str]) -> TradingCycleResult:
        cycle_id = f"cycle_{uuid.uuid4().hex[:10]}"
        result = TradingCycleResult(cycle_id=cycle_id, timestamp=time.time())

        # 1. Fetch market data for all assets
        market_data = {}
        for asset in assets:
            try:
                market_data[asset] = await self._fetch_market_data(asset)
            except Exception as e:
                result.errors.append(f"Market data failed for {asset}: {e}")

        if not market_data:
            return result

        # 2. Infer regime → curator selects profile → pattern subset
        regime = self._infer_regime(market_data)
        self._current_regime = regime

        # Check if curator should switch profile based on regime
        profile_map = {0: "standard", 1: "standard", 2: "defensive"}
        target_profile = profile_map.get(regime, "standard")
        if target_profile != self.curator.state.current_profile:
            switch_log = self.curator.request_switch(
                target_profile, f"Regime {regime} detected", int(time.time()), drawdown_breach=(regime==2)
            )
            if switch_log.get("outcome") == "applied":
                self._sync_patterns_from_curator()
                result.curator = {"profile_switch": switch_log}

        # 3. Process each asset
        for asset in assets:
            if asset in market_data:
                asset_result = await self._process_asset(asset, market_data, cycle_id)
                result.signals.extend(asset_result["signals"])
                result.decisions.extend(asset_result["decisions"])
                result.executions.extend(asset_result["executions"])
                result.errors.extend(asset_result["errors"])

        # 4. Record pattern metrics
        result.pattern_metrics = self.pattern_registry.get_metrics()
        result.regime = regime

        return result

    async def run(self, assets: list[str], interval_seconds: int = 300):
        logger.info(f"Starting {self.agent_id} with patterns: {self.pattern_registry.get_active_patterns()}")
        while True:
            try:
                result = await self.run_trading_cycle(assets)
                logger.info(f"Cycle complete: {len(result.executions)} execs, regime={result.regime}")
                if result.errors:
                    logger.warning(f"Errors: {result.errors}")
            except Exception as e:
                logger.error(f"Cycle error: {e}", exc_info=True)
            await asyncio.sleep(interval_seconds)