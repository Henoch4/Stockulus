"""
Risk gate + durable daily counters.

RiskGate: non-overridable pre-trade checks (position/loss/trade limits, kill
switch, freshness, fat-finger, reduce-only, confidence floor). The gate is the
"boring, deterministic, non-negotiable" layer — see execution.py docstring.

DurableDailyCounters: atomic JSON store backing the daily accumulators so a
process restart cannot reset per-day limits mid-day (Block F safety invariant).

Split out of execution.py (Block G): the risk layer is the authority boundary
you point a reviewer at to answer "where can an order be approved?"
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import OrderRequest

logger = logging.getLogger(__name__)


class DurableDailyCounters:
    """Atomic JSON-backed store for (agent_id, utc_day) -> accumulators.

    File path is taken from RISK_STATE_PATH (env) if set, else a tempfile dir
    location. Pass an explicit path in tests. Each instance owns the file;
    concurrent RiskGate instances in the same process are guarded by a class-
    level lock keyed by path.
    """

    _LOCKS: dict[str, threading.Lock] = {}
    _LOCKS_GUARD = threading.Lock()

    def __init__(self, path: str | None = None, enabled: bool = True):
        self.enabled = enabled
        if not enabled:
            self.path = None
            self._data: dict[str, dict] = {}
            self._lock = None
            return
        if path is None:
            path = os.environ.get("RISK_STATE_PATH", "").strip()
        if not path:
            path = os.path.join(tempfile.gettempdir(), "stockulus_risk_state.json")
        self.path = path
        self._data = self._load()
        with self._LOCKS_GUARD:
            self._lock = self._LOCKS.setdefault(path, threading.Lock())
        # Load persisted kill switch state from durable counters
        self._kill_switch_active = False
        self._kill_switch_reason = None
        self._kill_switch_activated_at = None
        if self.enabled:
            ks_active = self.get("__kill_switch__", "active", False)
            self._kill_switch_active = bool(ks_active)
            self._kill_switch_reason = self.get("__kill_switch__", "reason", None)
            self._kill_switch_activated_at = self.get("__kill_switch__", "timestamp", None)

    @classmethod
    def _for_path(cls, path: str) -> threading.Lock:
        with cls._LOCKS_GUARD:
            return cls._LOCKS.setdefault(path, threading.Lock())

    def _load(self) -> dict[str, dict]:
        if not self.path:
            return {}
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as e:
            # Corrupt or unreadable state must NOT be trusted silently — a
            # stale or half-written store could zero the counters and reopen
            # a breached limit. Refuse to load and start clean rather than
            # launder a bad file into a passing state.
            logger.warning(f"DurableDailyCounters: discarding unreadable store {self.path}: {e}")
        return {}

    def _persist(self) -> None:
        if not self.enabled or not self.path or not self._lock:
            return
        parent = os.path.dirname(self.path) or "."
        try:
            os.makedirs(parent, exist_ok=True)
            # write-then-rename so a crash never leaves a half-written file.
            fd, tmp = tempfile.mkstemp(dir=parent, prefix=".risk_state_")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self._data, f)
                os.replace(tmp, self.path)
            finally:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass
        except OSError as e:
            # Persistence failure is surfaced, not swallowed: if we can't write
            # the state file, the gate must not pretend the counters are saved.
            logger.error(f"DurableDailyCounters: failed to persist to {self.path}: {e}")
            # alerting import would go here if we had it
            # from ..alerting import send_alert
            # send_alert(...)

    def get(self, key: str, field: str, default):
        if not self.enabled or not self._lock:
            return default
        with self._lock:
            return self._data.get(key, {}).get(field, default)
    
    def set(self, key: str, active: bool | None = None, reason: str | None = None, timestamp: float | None = None) -> None:
        if not self.enabled or not self._lock:
            return
        with self._lock:
            entry = self._data.setdefault(key, {})
            if active is not None:
                entry["active"] = active
            if reason is not None:
                entry["reason"] = reason
            if timestamp is not None:
                entry["timestamp"] = timestamp
            self._persist()

    def increment(self, key: str, field: str, amount) -> None:
        if not self.enabled or not self._lock:
            return
        with self._lock:
            entry = self._data.setdefault(key, {})
            entry[field] = entry.get(field, 0 if isinstance(amount, (int, float)) else 0) + amount
            self._persist()

    def keys_with_prefix(self, prefix: str) -> list[str]:
        if not self.enabled or not self._lock:
            return []
        with self._lock:
            return sorted(k for k in self._data if k.startswith(prefix))

    def snapshot(self, key: str) -> dict:
        if not self.enabled or not self._lock:
            return {}
        with self._lock:
            return dict(self._data.get(key, {}))


@dataclass
class RiskCheckResult:
    approved: bool
    code: str
    reason: str


class RiskGate:
    """
    Non-overridable pre-trade risk gate.
    
    This is the Wall Street principle: "The strategy is allowed to be creative.
    The risk and control layer must be boring, deterministic, and non-negotiable."
    
    All thresholds are set at construction time and cannot be bypassed
    by the trading agent.
    """

    def __init__(
        self,
        max_position_usd: float = 100,           # devnet: $100 max
        max_daily_loss_usd: float = 20,          # devnet: $20 daily loss
        max_daily_trades: int = 10,
        max_daily_volume_usd: float = 1000,
        max_leverage: float = 1.0,               # stocks: 1x only
        max_slippage_pct: float = 1.0,
        min_confidence_bps: int = 7000,
        allowed_assets: list[str] | None = None,
        allowed_companions: list[str] | None = None,
        # --- Max price age ---
        max_price_age_seconds: float = 60.0,
        # --- Regime throttle (high-volatility governor) ---
        regime_throttle: bool = False,
        regime_band_pct: float = 5.0,
        regime_size_scale: float = 0.8,
        regime_buffer: int = 20,
        # --- Crash-safe daily counters ---
        counter_store: DurableDailyCounters | None = None,
        counter_store_path: str | None = None,
        counters_durable: bool = False,
        # --- Onchain source-of-truth hook (optional) ---
        onchain_logger=None,
        # --- Earnings blackout ---
        earnings_blackout: bool = True,
    ):
        self.max_position_usd = max_position_usd
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_daily_trades = max_daily_trades
        self.max_daily_volume_usd = max_daily_volume_usd
        self.max_leverage = max_leverage
        self.max_slippage_pct = max_slippage_pct
        self.min_confidence_bps = min_confidence_bps
        self.max_price_age_seconds = max_price_age_seconds
        self.earnings_blackout = earnings_blackout
        self.allowed_assets = allowed_assets or [
            "AAPLx", "TSLAx", "NVDAx",
            "AAPLx-DBC", "TSLAx-DBC", "NVDAx-DBC",
        ]
        self.allowed_companions = allowed_companions or []
        self.regime_throttle = regime_throttle
        self.regime_band_pct = regime_band_pct
        self.regime_size_scale = regime_size_scale
        self.regime_buffer = regime_buffer

        # Allowlist is exact match only: allowed_assets + allowed_companions.
        self._allowed_set: set[str] = set(self.allowed_assets) | set(self.allowed_companions)

        # Daily tracking — persisted so a restart does not reset per-day limits
        self._daily_volume: dict[str, float] = {}
        self._daily_loss: dict[str, float] = {}
        self._daily_trade_count: dict[str, int] = {}
        if counter_store is None:
            counter_store = DurableDailyCounters(
                path=counter_store_path, enabled=counters_durable
            )
        self._counters = counter_store
        self._onchain_logger = onchain_logger

        # --- Kill switch ---
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str | None = None
        self._kill_switch_activated_at: float | None = None

        # --- Regime throttle state ---
        self._price_buffer: dict[str, list[float]] = {}

        # Bootstrap in-memory caches from the persistent store
        self._rehydrate_store()
        if self._onchain_logger is not None:
            self.sync_with_onchain()

    def _rehydrate_store(self) -> None:
        if not self._counters.enabled:
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        loaded = False
        for raw_key in self._counters.keys_with_prefix(""):
            if not raw_key.endswith(f":{today}"):
                continue
            snap = self._counters.snapshot(raw_key)
            self._daily_volume[raw_key] = snap.get("volume", 0.0)
            self._daily_loss[raw_key] = snap.get("loss", 0.0)
            self._daily_trade_count[raw_key] = snap.get("trade_count", 0)
            loaded = True
        if loaded:
            logger.info("RiskGate rehydrated daily counters from store for the current UTC day")

    def sync_with_onchain(self) -> None:
        logger_obj = self._onchain_logger
        if logger_obj is None:
            return
        contract = getattr(logger_obj, "contract", None)
        if contract is None:
            return
        agent_address = getattr(logger_obj, "agent_address", None)
        if not agent_address:
            return
        try:
            onchain_ks = bool(contract.functions.killSwitchActive(agent_address).call())
            if onchain_ks and not self._kill_switch_active:
                reason = "onchain kill switch active for agent " + agent_address
                logger.warning(f"sync_with_onchain: tripping gate kill switch — {reason}")
                self.activate_kill_switch(reason)
        except Exception as e:
            logger.warning(f"sync_with_onchain: unable to read kill switch from contract: {e}")

    @staticmethod
    def _day_key(agent_id: str) -> str:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{agent_id}:{today}"

    def _day_keys(self, agent_id: str) -> list[str]:
        prefix = f"{agent_id}:"
        return sorted(k for k in self._daily_volume if k.startswith(prefix))

    def current_day_key(self, agent_id: str) -> str:
        return self._day_key(agent_id)

    def activate_kill_switch(self, reason: str) -> None:
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        self._kill_switch_activated_at = time.time()
        self._counters.set(
            key="__kill_switch__",
            active=True,
            reason=reason,
            timestamp=self._kill_switch_activated_at,
        )
        # alerting would go here

    def deactivate_kill_switch(self) -> None:
        self._kill_switch_active = False
        self._kill_switch_reason = None
        self._kill_switch_activated_at = None
        self._counters.set(
            key="__kill_switch__",
            active=False,
            reason=None,
            timestamp=None,
        )

    def kill_switch_status(self) -> dict:
        return {
            "active": self._kill_switch_active,
            "reason": self._kill_switch_reason,
            "activated_at": self._kill_switch_activated_at,
        }

    def observe_price(self, inst_id: str, price: float) -> None:
        buf = self._price_buffer.setdefault(inst_id, [])
        buf.append(price)
        if len(buf) > self.regime_buffer:
            buf.pop(0)

    def reset_price_buffer(self, inst_id: str | None = None) -> None:
        if inst_id is None:
            self._price_buffer.clear()
        else:
            self._price_buffer.pop(inst_id, None)

    def regime_scale(self, inst_id: str) -> float:
        if not self.regime_throttle:
            return 1.0
        buf = self._price_buffer.get(inst_id)
        if not buf:
            return self.regime_size_scale
        mean = sum(buf) / len(buf)
        if mean <= 0:
            return 1.0
        spread = (max(buf) - min(buf)) / mean * 100.0
        if spread <= self.regime_band_pct:
            return 1.0
        return self.regime_size_scale

    def regime_status(self, inst_id: str | None = None) -> dict:
        if inst_id is not None:
            return {
                "enabled": self.regime_throttle,
                "band_pct": self.regime_band_pct,
                "scale": self.regime_scale(inst_id),
                "window_size": len(self._price_buffer.get(inst_id, [])),
                "window_capacity": self.regime_buffer,
            }
        return {"enabled": self.regime_throttle, "band_pct": self.regime_band_pct}

    def _is_asset_allowed(self, inst_id: str) -> bool:
        # Check earnings blackout
        if self.earnings_blackout and hasattr(self, '_earnings_blacklist'):
            base = inst_id.split("-")[0].replace("x", "").upper()
            if base in self._earnings_blacklist:
                return False
        # Exact match OR base-symbol match (accepts both "AAPLx" and "AAPLx-DBC")
        return inst_id in self._allowed_set or inst_id.split("-")[0] in self._allowed_set

    def set_earnings_blacklist(self, symbols: list[str]) -> None:
        self._earnings_blacklist = {s.upper() for s in symbols}

    def check_order(
        self,
        order: OrderRequest,
        agent_id: str = "default",
        current_price: float | None = None,
        current_price_timestamp: float | None = None,
        current_position_side: str | None = None,
        unwind: bool = False,
        count_trade: bool = True,
    ) -> RiskCheckResult:
        # 0. Kill switch
        if self._kill_switch_active and not unwind:
            return RiskCheckResult(
                approved=False,
                code="KILL_SWITCH_ACTIVE",
                reason=f"Kill switch is active: {self._kill_switch_reason}",
            )
        if self._kill_switch_active and unwind:
            logger.warning(
                "KILL_SWITCH_BYPASS: admitting unwind order %s (%s) while kill "
                "switch is active (%s) — closing leg required to flatten exposure.",
                order.client_oid, order.inst_id, self._kill_switch_reason,
            )

        # 1. Asset allowlist
        if not self._is_asset_allowed(order.inst_id):
            return RiskCheckResult(
                approved=False,
                code="ASSET_NOT_ALLOWED",
                reason=f"{order.inst_id} not in allowlist: {self.allowed_assets}",
            )

        # 2. Confidence floor
        if order.confidence_bps is None:
            logger.warning(
                "CONFIDENCE_MISSING: order %s (%s %s %s) has no confidence_bps; "
                "the %d bps floor is not being enforced on it.",
                order.client_oid, order.side, order.order_type, order.inst_id,
                self.min_confidence_bps,
            )
        elif order.confidence_bps < self.min_confidence_bps:
            return RiskCheckResult(
                approved=False,
                code="CONFIDENCE_TOO_LOW",
                reason=(
                    f"Signal confidence {order.confidence_bps} bps below the "
                    f"{self.min_confidence_bps} bps floor — the risk gate does "
                    f"not trade on weak signals."
                ),
            )

        # 3. Position size limit (scaled by regime throttle)
        try:
            size_usd = float(order.size)
        except (ValueError, TypeError):
            return RiskCheckResult(
                approved=False,
                code="INVALID_ORDER_SIZE",
                reason=f"Order size {order.size!r} is not a valid number.",
            )
        if size_usd < 0:
            return RiskCheckResult(
                approved=False,
                code="INVALID_ORDER_SIZE",
                reason=f"Order size {order.size!r} cannot be negative.",
            )

        effective_max = self.max_position_usd * self.regime_scale(order.inst_id)
        if size_usd > effective_max:
            if effective_max < self.max_position_usd:
                return RiskCheckResult(
                    approved=False,
                    code="REGIME_SIZE_CAP",
                    reason=(
                        f"Position ${size_usd:.2f} exceeds regime-scaled cap "
                        f"${effective_max:.2f} (max ${self.max_position_usd:.2f} "
                        f"x regime scale {self.regime_scale(order.inst_id):.2f}). "
                        f"High-volatility regime — throttle is active."
                    ),
                )
            return RiskCheckResult(
                approved=False,
                code="POSITION_TOO_LARGE",
                reason=f"Position ${size_usd:.2f} exceeds max ${self.max_position_usd:.2f}",
            )

        # 4. Daily trade count
        key = self._day_key(agent_id)
        if not unwind and self._daily_trade_count.get(key, 0) >= self.max_daily_trades:
            return RiskCheckResult(
                approved=False,
                code="DAILY_TRADE_LIMIT_EXCEEDED",
                reason=(
                    f"Agent has already placed "
                    f"{self._daily_trade_count.get(key, 0)} "
                    f"trades today (max {self.max_daily_trades})"
                ),
            )

        # 4b. Daily volume limit
        if not unwind:
            current_volume = self._daily_volume.get(key, 0.0)
            if current_volume + size_usd > self.max_daily_volume_usd:
                return RiskCheckResult(
                    approved=False,
                    code="DAILY_VOLUME_LIMIT_EXCEEDED",
                    reason=(
                        f"Daily volume ${current_volume:.2f} + order ${size_usd:.2f} "
                        f"would exceed limit ${self.max_daily_volume_usd:.2f}"
                    ),
                )

        # 5. Daily loss limit
        current_loss = self._daily_loss.get(key, 0.0)
        if current_loss >= self.max_daily_loss_usd:
            return RiskCheckResult(
                approved=False,
                code="DAILY_LOSS_LIMIT_EXCEEDED",
                reason=(
                    f"Daily loss ${current_loss:.2f} >= "
                    f"limit ${self.max_daily_loss_usd:.2f}"
                ),
            )

        # 6. Fat-finger / price sanity check
        try:
            limit_px = float(order.px) if order.px else None
        except (ValueError, TypeError):
            limit_px = None

        if limit_px is not None and current_price is not None and current_price > 0:
            deviation_pct = abs(limit_px - current_price) / current_price * 100
            if deviation_pct > 20.0:
                return RiskCheckResult(
                    approved=False,
                    code="FAT_FINGER_REJECTED",
                    reason=(
                        f"Limit price {limit_px:.2f} deviates {deviation_pct:.1f}% "
                        f"from current price {current_price:.2f} — rejected as a "
                        f"likely input error, not a normal slippage case."
                    ),
                )

        # 6b. Fat-finger for market orders using intended_price
        if order.order_type == "market" and order.intended_price is not None:
            if current_price is None or current_price <= 0:
                return RiskCheckResult(
                    approved=False,
                    code="NO_PRICE_REFERENCE",
                    reason=(
                        "Market order submitted with intended_price but no current "
                        "market price to check against — cannot verify fat-finger."
                    ),
                )
            deviation_pct = abs(order.intended_price - current_price) / current_price * 100
            if deviation_pct > self.max_slippage_pct:
                return RiskCheckResult(
                    approved=False,
                    code="FAT_FINGER_REJECTED",
                    reason=(
                        f"Intended price {order.intended_price:.2f} deviates "
                        f"{deviation_pct:.2f}% from current price {current_price:.2f}, "
                        f"exceeding the {self.max_slippage_pct:.2f}% collar."
                    ),
                )

        # 6c. Leverage cap
        if order.leverage is not None:
            try:
                declared_leverage = float(order.leverage)
            except (ValueError, TypeError):
                return RiskCheckResult(
                    approved=False,
                    code="INVALID_LEVERAGE",
                    reason=f"Order leverage {order.leverage!r} is not a valid number.",
                )
            if declared_leverage <= 0:
                return RiskCheckResult(
                    approved=False,
                    code="INVALID_LEVERAGE",
                    reason=f"Order leverage {declared_leverage} must be positive.",
                )
            if declared_leverage > self.max_leverage:
                return RiskCheckResult(
                    approved=False,
                    code="LEVERAGE_EXCEEDED",
                    reason=(
                        f"Declared leverage {declared_leverage:.2f}x exceeds the "
                        f"{self.max_leverage:.2f}x cap — this gate does not "
                        f"lever past its configured maximum."
                    ),
                )

        # 7. Slippage / price collar (for limit orders)
        if order.order_type == "limit" and limit_px is not None:
            if current_price is None or current_price <= 0:
                return RiskCheckResult(
                    approved=False,
                    code="NO_PRICE_REFERENCE",
                    reason=(
                        "Limit order submitted without a current market price to "
                        "check slippage against — cannot verify the price collar."
                    ),
                )
            slippage_pct = abs(limit_px - current_price) / current_price * 100
            if slippage_pct > self.max_slippage_pct:
                return RiskCheckResult(
                    approved=False,
                    code="SLIPPAGE_EXCEEDED",
                    reason=(
                        f"Limit price {limit_px:.2f} is {slippage_pct:.2f}% away "
                        f"from current price {current_price:.2f}, exceeding the "
                        f"{self.max_slippage_pct:.2f}% collar."
                    ),
                )

        # 8. Reduce-only enforcement
        if current_position_side == "long" and order.side == "sell" and not order.reduce_only:
            return RiskCheckResult(
                approved=False,
                code="REDUCE_ONLY_VIOLATION",
                reason=(
                    "Sell order against an existing long position must set "
                    "reduce_only=True — this gate does not allow flipping a "
                    "position from long to short in a single unmarked order."
                ),
            )
        if current_position_side == "short" and order.side == "buy" and not order.reduce_only:
            return RiskCheckResult(
                approved=False,
                code="REDUCE_ONLY_VIOLATION",
                reason=(
                    "Buy order against an existing short position must set "
                    "reduce_only=True — this gate does not allow flipping a "
                    "position from short to long in a single unmarked order."
                ),
            )

        # 9. Price-freshness gate
        if current_price is None or current_price <= 0:
            return RiskCheckResult(
                approved=False,
                code="NO_PRICE_REFERENCE",
                reason=(
                    "Order submitted without a current market price to verify "
                    "against — cannot check the price collar or freshness."
                ),
            )
        now = time.time()
        price_age = (
            now - current_price_timestamp
            if current_price_timestamp is not None
            else float("inf")
        )
        if price_age > self.max_price_age_seconds:
            return RiskCheckResult(
                approved=False,
                code="STALE_PRICE",
                reason=(
                    f"Reference price {current_price} is "
                    f"{price_age:.1f}s old (cap {self.max_price_age_seconds:.0f}s). "
                    f"Price feed is not fresh — refusing to trade on stale data."
                ),
            )

        # 10. Daily trade count — persisted
        if count_trade and not unwind:
            count = self._daily_trade_count.get(key, 0) + 1
            self._daily_trade_count[key] = count
            self._counters.increment(key, "trade_count", 1)
        return RiskCheckResult(
            approved=True,
            code="APPROVED",
            reason="All checks passed",
        )

    def report_loss(self, agent_id: str, loss_usd: float, day_key: str | None = None):
        key = day_key or self._day_key(agent_id)
        loss = self._daily_loss.get(key, 0.0) + loss_usd
        self._daily_loss[key] = loss
        self._counters.increment(key, "loss", loss_usd)
        if loss >= self.max_daily_loss_usd and not self._kill_switch_active:
            self.activate_kill_switch(
                reason=(
                    f"Auto-triggered: agent {agent_id} daily loss "
                    f"${loss:.2f} reached limit "
                    f"${self.max_daily_loss_usd:.2f}"
                )
            )

    def report_volume(self, agent_id: str, volume_usd: float, day_key: str | None = None):
        key = day_key or self._day_key(agent_id)
        vol = self._daily_volume.get(key, 0.0) + volume_usd
        self._daily_volume[key] = vol
        self._counters.increment(key, "volume", volume_usd)

    def get_daily_stats(self, agent_id: str) -> dict:
        key = self._day_key(agent_id)
        return {
            "volume": self._daily_volume.get(key, 0.0),
            "loss": self._daily_loss.get(key, 0.0),
            "trade_count": self._daily_trade_count.get(key, 0),
            "volume_limit": self.max_position_usd * self.max_daily_trades,
            "loss_limit": self.max_daily_loss_usd,
            "trade_count_limit": self.max_daily_trades,
        }

    def compute_risk_hash(self) -> str:
        params = {
            "max_position_usd": self.max_position_usd,
            "max_daily_loss_usd": self.max_daily_loss_usd,
            "max_daily_trades": self.max_daily_trades,
            "max_daily_volume_usd": self.max_daily_volume_usd,
            "max_leverage": self.max_leverage,
            "max_slippage_pct": self.max_slippage_pct,
            "min_confidence_bps": self.min_confidence_bps,
            "max_price_age_seconds": self.max_price_age_seconds,
            "allowed_assets": sorted(self.allowed_assets),
            "allowed_companions": sorted(self.allowed_companions),
            "regime_throttle": self.regime_throttle,
            "regime_band_pct": self.regime_band_pct,
            "regime_size_scale": self.regime_size_scale,
            "earnings_blackout": self.earnings_blackout,
        }
        serialized = json.dumps(params, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()