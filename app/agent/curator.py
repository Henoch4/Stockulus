"""
Curator / meta agent: selects between a small, FIXED set of pre-bounded
strategy profiles. It never writes raw risk/sizing parameters -- only a
profile name, validated against the allowlist. Includes cooldown and
automatic revert-on-underperformance so "advisory-only" is a checkable,
enforced mechanism rather than a promise.

Profiles live in config/profiles.yaml under the trader's risk-gate
vocabulary (confidence floors in bps, position-size multiplier, max
leverage, enabled signal set).

Integration mode is *default-passthrough*: the selected profile is the
default for each knob, and an operator-supplied env override for a knob
wins ONLY when it is explicitly set. See `apply_env_overrides`.

Extended with regime-aware auto-switching (HMM-driven).

Ported from the sibling `trading_system` MVP (agents/curator_agent.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from .audit_trail import AuditLog


# ─── Regime → Curator Profile Map ───
# HMM regime (0=low/range, 1=mid/trend, 2=high/cascade) → curator profile
REGIME_PROFILE_MAP = {
    0: "standard",   # low vol / rangebound → provide LP, standard carry
    1: "standard",   # mid vol / trending → active delta rebalance
    2: "defensive",  # high vol / cascade → pull LP, risk-off
}


@dataclass
class CuratorState:
    current_profile: str
    last_switch_cycle: int = -10_000
    switch_history: list[dict] = field(default_factory=list)
    # Trailing window of PnLs since last switch (for auto-revert trigger).
    pnl_window: list[float] = field(default_factory=list)
    trades_since_switch: int = 0
    previous_profile: str | None = None
    # True when the current profile was forced by the drawdown breaker.
    # Auto-revert never reverts OUT of a forced-defensive state.
    forced_defensive: bool = False
    # Last regime that triggered a profile switch
    last_regime: int | None = None


class CuratorAgent:
    def __init__(
        self,
        profiles_path: str | Path = Path(__file__).resolve().parents[2] / "config" / "profiles.yaml",
        audit_log: AuditLog | None = None,
    ):
        with open(profiles_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        self.profiles: dict = cfg["profiles"]
        self.default_profile: str = cfg["default_profile"]
        self.cooldown_cycles: int = cfg["cooldown_cycles"]
        self.auto_revert_lookback_trades: int = cfg["auto_revert_lookback_trades"]
        self.auto_revert_threshold_pnl: float = cfg["auto_revert_threshold_pnl"]

        assert self.default_profile in self.profiles, "default_profile must be in the allowlist"
        self.state = CuratorState(current_profile=self.default_profile)
        self.audit_log = audit_log

    def active_profile(self) -> dict:
        return self.profiles[self.state.current_profile]

    def request_switch(self, proposed_profile: str, rationale: str, cycle: int,
                        drawdown_breach: bool) -> dict:
        """Returns a log dict describing what happened -- the auditable
        record for this cycle. Every switch attempt is logged, whether it
        was applied, rejected, or overridden."""
        log = {
            "cycle": cycle,
            "proposed_profile": proposed_profile,
            "rationale": rationale,
            "prior_profile": self.state.current_profile,
            "outcome": None,
        }

        # Drawdown circuit breaker always wins -- the curator cannot override
        # this even by "choosing" a different profile.
        if drawdown_breach:
            self._apply_switch("defensive", cycle, forced=True)
            log["outcome"] = "forced_defensive_by_drawdown_breaker"
            self._record(log)
            return log

        # Whitelist check -- an off-allowlist name is rejected, not coerced.
        if proposed_profile not in self.profiles:
            log["outcome"] = "rejected_not_on_allowlist"
            self._record(log)
            return log

        if proposed_profile == self.state.current_profile:
            log["outcome"] = "no_change"
            self._record(log)
            return log

        if cycle - self.state.last_switch_cycle < self.cooldown_cycles:
            log["outcome"] = "rejected_cooldown_active"
            self._record(log)
            return log

        self._apply_switch(proposed_profile, cycle, forced=False)
        log["outcome"] = "applied"
        self._record(log)
        return log

    def auto_switch_on_regime(self, regime: int, cycle: int) -> dict | None:
        """
        Automatically switch curator profile based on HMM regime.
        Called by agent each cycle. Returns switch log if switched, None otherwise.
        """
        target_profile = REGIME_PROFILE_MAP.get(regime, "standard")
        if target_profile == self.state.current_profile:
            return None  # no change needed

        # Check cooldown
        if cycle - self.state.last_switch_cycle < self.cooldown_cycles:
            return {"outcome": "rejected_cooldown_active", "target_profile": target_profile}

        rationale = f"Regime {regime} detected → {target_profile}"
        drawdown_breach = (regime == 2)  # high vol = defensive
        log = self.request_switch(target_profile, rationale, cycle, drawdown_breach)
        if log.get("outcome") == "applied":
            self.state.last_regime = regime
        return log

    def _apply_switch(self, profile: str, cycle: int, forced: bool):
        self.state.previous_profile = self.state.current_profile
        self.state.current_profile = profile
        self.state.last_switch_cycle = cycle
        self.state.pnl_window.clear()
        self.state.trades_since_switch = 0
        # Track if we were forced into defensive — auto-revert never reverts out of this.
        self.state.forced_defensive = forced and profile == "defensive"

    def record_trade_pnl(self, pnl: float, cycle: int) -> dict | None:
        """Feed realized PnL back to the curator. If the trailing-window PnL
        since the last switch breaches the auto-revert threshold, revert
        automatically -- this does not wait for a human to notice.

        Never auto-reverts OUT of forced-defensive (drawdown-breaker state);
        that transition requires a manual operator action.
        """
        # Maintain trailing window of PnLs (fixed size = lookback_trades)
        self.state.pnl_window.append(pnl)
        if len(self.state.pnl_window) > self.auto_revert_lookback_trades:
            self.state.pnl_window.pop(0)
        self.state.trades_since_switch += 1

        # Only check auto-revert once we have a full window
        if (len(self.state.pnl_window) >= self.auto_revert_lookback_trades
                and self.state.previous_profile is not None
                and not self.state.forced_defensive):
            trailing_pnl = sum(self.state.pnl_window)
            if trailing_pnl < self.auto_revert_threshold_pnl:
                reverted_to = self.state.previous_profile
                log = {
                    "cycle": cycle,
                    "event": "auto_revert",
                    "from_profile": self.state.current_profile,
                    "to_profile": reverted_to,
                    "trailing_pnl": trailing_pnl,
                }
                # Auto-revert is never forced
                self._apply_switch(reverted_to, cycle, forced=False)
                self._record(log)
                return log
        return None

    def _record(self, log: dict):
        self.state.switch_history.append(log)
        if self.audit_log:
            self.audit_log.write("curator_switch", log)

    def get_dashboard_data(self) -> dict:
        """Return curator state for dashboard/metrics endpoint."""
        return {
            "current_profile": self.state.current_profile,
            "profile_config": self.active_profile(),
            "last_switch_cycle": self.state.last_switch_cycle,
            "trades_since_switch": self.state.trades_since_switch,
            "forced_defensive": self.state.forced_defensive,
            "last_regime": self.state.last_regime,
            "pnl_window": self.state.pnl_window[-10:],  # last 10 trades
            "trailing_pnl": sum(self.state.pnl_window) if self.state.pnl_window else 0.0,
            "switch_history": self.state.switch_history[-20:],  # last 20 switches
        }


def apply_env_overrides(profile: dict, overrides: dict[str, str | None],
                        casters: dict[str, Callable] | None = None) -> dict:
    """
    Default-passthrough for curator knobs.

    The profile value is the default for every knob; an operator-set env var
    for a knob wins ONLY when it is explicitly provided (non-None). Unset or
    empty env vars leave the profile value untouched, so a partial env
    configuration never silently zeroes a knob.

    `casters` maps knob name -> converter (e.g. int/float). Unknown knobs are
    ignored, and a caster failure is ignored too -- a bad env value must not
    be able to break the trading loop; it just falls back to the profile.
    """
    resolved = dict(profile)
    casters = casters or {}
    for knob, raw in overrides.items():
        if raw is None or raw == "" or knob not in profile:
            continue
        try:
            resolved[knob] = (casters.get(knob, str))(raw)
        except (ValueError, TypeError):
            continue
    return resolved