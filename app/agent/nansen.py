"""Nansen on-chain intelligence adapter — env-gated, neutral without a key.

Phase C integration (BUILD_PLAN §10.1). Wraps the `nansen` CLI (npm `nansen-cli`)
via subprocess — same pattern as meteora_executor.py — so no new Python deps.

Auth: NANSEN_API_KEY env (see Nansen skill metadata: primaryEnv NANSEN_API_KEY,
binary `nansen`). Missing key OR missing binary → every method returns a
documented neutral default. Importing this module never touches the network.

Command surface (from nansen-cli skills/nansen-token-screener/SKILL.md):
  screener:        nansen research token screener --chain solana --timeframe 24h [--smart-money]
  top-tokens:      nansen research token top-tokens [--market-cap largecap]
  sm-holdings:     nansen research smart-money holdings --chain solana
  indicators:      nansen research token indicators --token ADDR --chain solana
  flow-intel:      nansen research token flow-intelligence --token ADDR --chain solana
                   (credit-heavy — finalists only, never a first pass)

Mappings into Tarstrade signals:
  flow-intelligence labels {smart_trader, whale, exchange, fresh_wallets}
      → onchain_flow_signal(whale_net_flow_usd, exchange_reserve_change_pct, ...)
  indicators.concentration_risk → holder-concentration scream filter (EXPANSION_ROADMAP)
  indicators risk/reward scores → regime/curator context (skip when empty — not an error)
  screener/top-tokens → curator carry-universe screening (min liquidity for 16bps hurdle)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHAIN = "solana"
CACHE_TTL_S = 24 * 3600


def _cache_dir() -> Path:
    d = Path(os.getenv("NANSEN_CACHE_DIR", "") or "").expanduser()
    if not d.name:
        import tempfile

        d = Path(tempfile.gettempdir()) / "stockulus_nansen"
    d.mkdir(parents=True, exist_ok=True)
    return d


class NansenClient:
    """Thin CLI wrapper. All reads cached 24h (file cache keeps x402/API pennies per cycle)."""

    def __init__(self, api_key: str | None = None, chain: str = CHAIN):
        self.api_key = api_key or os.getenv("NANSEN_API_KEY", "")
        self.chain = chain
        self._bin = shutil.which("nansen")

    @property
    def available(self) -> bool:
        """False when key or binary missing — callers must use neutral defaults."""
        key = (self.api_key or "").strip()
        return bool(key) and not key.startswith("nansen_xxx") and self._bin is not None

    def _cache_path(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() else "_" for c in f"{self.chain}_{name}")[:80]
        return _cache_dir() / f"{safe}.json"

    def _cached(self, name: str) -> Any | None:
        try:
            p = self._cache_path(name)
            if not p.exists() or time.time() - p.stat().st_mtime > CACHE_TTL_S:
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _store(self, name: str, data: Any) -> None:
        try:
            self._cache_path(name).write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    def _run(self, *args: str, cache_name: str | None = None, timeout: int = 60) -> Any | None:
        """Run `nansen ...`, parse stdout JSON. None on any failure (key/binary/RPC)."""
        if not self.available:
            return None
        if cache_name:
            hit = self._cached(cache_name)
            if hit is not None:
                return hit
        env = {**os.environ, "NANSEN_API_KEY": self.api_key, "CHAIN": self.chain}
        try:
            proc = subprocess.run(
                [self._bin, *args], capture_output=True, text=True, env=env, timeout=timeout
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f"nansen CLI failed: {e}")
            return None
        if proc.returncode != 0:
            logger.debug(f"nansen CLI error: {proc.stderr[:200]}")
            return None
        try:
            data = json.loads(proc.stdout.strip())
        except ValueError:
            return None
        if cache_name:
            self._store(cache_name, data)
        return data

    # --- Discovery (cheap first pass) ---

    def top_tokens(self, market_cap: str | None = None, limit: int = 25) -> list[dict]:
        args = ["research", "token", "top-tokens", "--limit", str(limit)]
        if market_cap:
            args += ["--market-cap", market_cap]
        data = self._run(*args, cache_name=f"top_{market_cap or 'all'}_{limit}")
        return _as_list(data)

    def screener(
        self, timeframe: str = "24h", smart_money: bool = False, limit: int = 20
    ) -> list[dict]:
        args = ["research", "token", "screener", "--chain", self.chain,
                "--timeframe", timeframe, "--limit", str(limit)]
        if smart_money:
            args.append("--smart-money")
        data = self._run(*args, cache_name=f"screener_{timeframe}_{int(smart_money)}_{limit}")
        return _as_list(data)

    def smart_money_holdings(self, limit: int = 20) -> list[dict]:
        data = self._run(
            "research", "smart-money", "holdings",
            "--chain", self.chain, "--labels", "Smart Trader", "--limit", str(limit),
            cache_name=f"sm_holdings_{limit}",
        )
        return _as_list(data)

    # --- Per-token drill-down (finalists only; flow-intel is credit-heavy) ---

    def token_indicators(self, token_mint: str) -> dict:
        """Risk/reward scores. Empty dict is normal (not an error)."""
        data = self._run(
            "research", "token", "indicators",
            "--token", token_mint, "--chain", self.chain,
            cache_name=f"indicators_{token_mint[:16]}",
        )
        return data if isinstance(data, dict) else {}

    def flow_intelligence(self, token_mint: str) -> dict:
        """Net-flow USD per label {smart_trader, whale, exchange, fresh_wallets, ...}."""
        data = self._run(
            "research", "token", "flow-intelligence",
            "--token", token_mint, "--chain", self.chain,
            cache_name=f"flow_{token_mint[:16]}",
        )
        return data if isinstance(data, dict) else {}

    # --- Mapping into Tarstrade signal inputs ---

    def onchain_flow_inputs(self, token_mint: str) -> dict:
        """Map flow-intelligence → onchain_flow_signal() kwargs.

        Neutral zeros when unavailable — the ensemble treats missing flow as
        no-evidence, never as a signal (same fallback as regime_hmm w/o hmmlearn).
        """
        neutral = {
            "whale_net_flow_usd": 0.0,
            "exchange_reserve_change_pct": 0.0,
            "stablecoin_supply_change_pct": 0.0,
        }
        flows = self.flow_intelligence(token_mint)
        if not flows:
            return neutral
        labels = flows.get("net_flow_usd", flows) if isinstance(flows, dict) else {}
        try:
            return {
                "whale_net_flow_usd": float(labels.get("whale", 0.0) or 0.0)
                + float(labels.get("smart_trader", 0.0) or 0.0),
                # Exchange net inflow GLASSNODE-style proxy: +inflow = distribution.
                "exchange_reserve_change_pct": _sign_pct(labels.get("exchange", 0.0)),
                "stablecoin_supply_change_pct": 0.0,  # stablecoin leg needs screener-level data
            }
        except (TypeError, ValueError):
            return neutral

    def concentration_flag(self, token_mint: str) -> dict:
        """Holder-concentration scream filter (EXPANSION_ROADMAP pattern).

        Returns {"concentrated": bool, "reason": str}. Unavailable → not concentrated.
        """
        ind = self.token_indicators(token_mint)
        risk = (ind.get("concentration_risk") or ind.get("concentration") or "")
        if isinstance(risk, dict):
            sig = str(risk.get("signal", "")).lower()
            if sig == "bearish" or "high" in str(risk.get("score", "")).lower():
                return {"concentrated": True, "reason": f"nansen concentration: {risk}"}
        return {"concentrated": False, "reason": "no concentration signal"}


def _as_list(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        for key in ("tokens", "data", "items", "nodes", "results"):
            if isinstance(data.get(key), list):
                return [d for d in data[key] if isinstance(d, dict)]
    return []


def _sign_pct(value: Any) -> float:
    try:
        v = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if v == 0:
        return 0.0
    # Direction only at this granularity (flow-intel gives levels, not % changes).
    return 1.0 if v > 0 else -1.0
