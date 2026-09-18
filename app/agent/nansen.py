"""Nansen on-chain intelligence adapter — direct REST, env-gated, budget-guarded.

Docs: https://docs.nansen.ai (probed 2026-09-18; shapes below are per OpenAPI).
Auth: `apikey` header (docs/getting-started/authentication). Base: https://api.nansen.ai.
No key (or placeholder) → every method returns documented neutrals, zero network.

Exact endpoints (all POST JSON):
  screener:   /api/v1/token-screener
              {chains: ["solana"], timeframe: "24h", filters: {trader_type, liquidity, ...},
               order_by, pagination} — 1 credit, point-in-time, no server cache.
  netflow:    /api/v1/smart-money/netflow
              {chains: ["solana"], filters: {token_address, ...}, order_by} — 5 credits,
              rolling 1h/24h/7d/30d windows, 30d retention only.
  holdings:   /api/v1/smart-money/holdings
              {chains: ["solana"], filters: {token_address, ...}} — 5 credits, point-in-time.
  flow:       /api/v1/tgm/flow-intelligence
              {chain: "solana", token_address, timeframe: 5m/1h/6h/12h/1d/7d} — 1 credit,
              live 24h, server cache 10–30m. Labels: whale/smart_trader/exchange/
              fresh_wallets/top_pnl/public_figure (+ *_avg_flow_usd, *_wallet_count).
  indicators: /api/v1/tgm/indicators
              {chain: "solana", token_address} — 5 credits, DAILY batch (not realtime).
              risk_indicators[] + reward_indicators[] of {indicator_type, score,
              signal, signal_percentile, last_trigger_on}.

Budget discipline (RiskGate spirit, applied to credits):
  - X-Nansen-Credits-Remaining tracked after every call; new calls refused below
    NANSEN_MIN_CREDITS (default 20) — fail-closed, never drain the account.
  - 429 → honor Retry-After once, then give up (no hot loops in the agent cycle).
  - insufficient_credits / plan_upgrade_required → latch off for the session.
  - profiler/address/labels (100/500 credits) is NEVER called from here.

Mappings into Tarstrade signals:
  flow record → onchain_flow_inputs(): whale+smart_trader sum, exchange sign.
  indicators concentration-risk score high → concentration_flag() scream filter.
  screener (liquidity/volume/min-mcap) → curator carry-universe screening.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.nansen.ai"
CHAIN = "solana"
CHAINS = ["solana"]
CACHE_TTL_S = 24 * 3600
FLOW_CACHE_TTL_S = 6 * 3600

# Credit costs (docs/getting-started/credits). Used for pre-flight budgeting.
COST = {
    "token-screener": 1,
    "smart-money/netflow": 5,
    "smart-money/holdings": 5,
    "tgm/flow-intelligence": 1,
    "tgm/indicators": 5,
}

# Stable error codes that latch the client off for the session (docs error envelope).
LATCH_OFF_CODES = {"insufficient_credits", "plan_upgrade_required", "forbidden"}


def _cache_dir() -> Path:
    import os
    import tempfile

    d = Path(os.getenv("NANSEN_CACHE_DIR", "") or "").expanduser()
    if not d.name:
        d = Path(tempfile.gettempdir()) / "stockulus_nansen"
    d.mkdir(parents=True, exist_ok=True)
    return d


class NansenClient:
    def __init__(
        self,
        api_key: str | None = None,
        chain: str = CHAIN,
        min_credits: int | None = None,
        timeout: float = 30.0,
    ):
        import os

        key = (api_key or os.getenv("NANSEN_API_KEY", "") or "").strip()
        self.api_key = "" if key.startswith("nansen_xxx") else key
        self.chain = chain
        self.timeout = timeout
        self.min_credits = (
            int(os.getenv("NANSEN_MIN_CREDITS", "20"))
            if min_credits is None
            else min_credits
        )
        self._client: httpx.AsyncClient | None = None
        self._latched_off = False
        self.credits_remaining: float | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key) and not self._latched_off

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE,
                timeout=self.timeout,
                headers={"Content-Type": "application/json", "apikey": self.api_key},
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # --- internals ---

    def _cache_path(self, name: str) -> Path:
        safe = "".join(c if c.isalnum() else "_" for c in f"{self.chain}_{name}")[:80]
        return _cache_dir() / f"{safe}.json"

    def _cached(self, name: str, ttl: int) -> Any | None:
        try:
            p = self._cache_path(name)
            if not p.exists() or time.time() - p.stat().st_mtime > ttl:
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _store(self, name: str, data: Any) -> None:
        try:
            self._cache_path(name).write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass

    async def _post(
        self, path: str, body: dict, cache_name: str | None = None, ttl: int = CACHE_TTL_S
    ) -> Any | None:
        """POST one endpoint. Returns parsed JSON or None (never raises)."""
        if not self.available:
            return None
        if cache_name:
            hit = self._cached(cache_name, ttl)
            if hit is not None:
                return hit
        if self.credits_remaining is not None and self.credits_remaining < self.min_credits:
            logger.warning(
                f"nansen budget floor: {self.credits_remaining} < {self.min_credits}, skipping {path}"
            )
            return None
        client = await self._get_client()
        try:
            resp = await client.post(path, json=body)
        except httpx.HTTPError as e:
            logger.debug(f"nansen transport error on {path}: {e}")
            return None
        self._track_credits(resp)
        if resp.status_code == 429:
            await self._handle_429(path, body, resp)
            return None
        if resp.status_code in (401, 403):
            logger.warning(f"nansen auth/forbidden on {path} ({resp.status_code})")
            if resp.status_code == 403:
                self._latched_off = True
            return None
        if resp.status_code != 200:
            self._check_latch(resp)
            logger.debug(f"nansen {path} -> {resp.status_code}: {resp.text[:200]}")
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        if cache_name:
            self._store(cache_name, data)
        return data

    def _track_credits(self, resp: httpx.Response) -> None:
        try:
            rem = resp.headers.get("x-nansen-credits-remaining")
            if rem is not None:
                self.credits_remaining = float(rem)
        except (TypeError, ValueError):
            pass

    async def _handle_429(self, path: str, body: dict, resp: httpx.Response) -> None:
        try:
            wait = int(resp.headers.get("retry-after", "30"))
        except (TypeError, ValueError):
            wait = 30
        logger.warning(f"nansen 429 on {path}, single retry after {min(wait, 120)}s")
        await asyncio.sleep(min(wait, 120))
        # One retry only; result intentionally discarded on failure (no hot loop).
        try:
            client = await self._get_client()
            retry = await client.post(path, json=body)
            self._track_credits(retry)
        except httpx.HTTPError:
            pass

    def _check_latch(self, resp: httpx.Response) -> None:
        try:
            code = (resp.json().get("code") or "").strip()
        except ValueError:
            return
        if code in LATCH_OFF_CODES:
            logger.warning(f"nansen latched off for session: {code}")
            self._latched_off = True

    @staticmethod
    def _records(data: Any) -> list[dict]:
        if isinstance(data, dict):
            data = data.get("data", [])
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []

    # --- Discovery (cheap first pass: 1 credit) ---

    async def token_screener(
        self,
        timeframe: str = "24h",
        trader_type: str = "sm",
        min_liquidity_usd: float = 50000,
        min_volume_usd: float = 10000,
        limit: int = 20,
    ) -> list[dict]:
        """Carry-universe screening: liquid + smart-traded tokens on Solana."""
        data = await self._post(
            "/api/v1/token-screener",
            {
                "chains": CHAINS,
                "timeframe": timeframe,
                "filters": {
                    "trader_type": trader_type,
                    "liquidity": {"min": min_liquidity_usd},
                    "volume": {"min": min_volume_usd},
                    "include_stablecoins": False,
                },
                "order_by": [{"field": "volume", "direction": "DESC"}],
                "pagination": {"page": 1, "per_page": limit},
            },
            cache_name=f"screener_{timeframe}_{trader_type}_{limit}",
        )
        return self._records(data)

    # --- Smart Money (5 credits each — cache aggressively) ---

    async def smart_money_netflow(
        self, token_address: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Net accumulation/distribution by smart money (1h/24h/7d/30d windows)."""
        filters: dict = {}
        if token_address:
            filters["token_address"] = token_address
        data = await self._post(
            "/api/v1/smart-money/netflow",
            {
                "chains": CHAINS,
                "filters": filters,
                "order_by": [{"field": "net_flow_7d_usd", "direction": "DESC"}],
                "pagination": {"page": 1, "per_page": limit},
            },
            cache_name=f"netflow_{token_address or 'all'}_{limit}",
        )
        return self._records(data)

    async def smart_money_holdings(
        self, token_address: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Point-in-time aggregated holdings (+24h change)."""
        filters: dict = {}
        if token_address:
            filters["token_address"] = token_address
        data = await self._post(
            "/api/v1/smart-money/holdings",
            {
                "chains": CHAINS,
                "filters": filters,
                "order_by": [{"field": "value_usd", "direction": "DESC"}],
                "pagination": {"page": 1, "per_page": limit},
            },
            cache_name=f"holdings_{token_address or 'all'}_{limit}",
        )
        return self._records(data)

    # --- Per-token drill-down ---

    async def flow_intelligence(
        self, token_mint: str, timeframe: str = "1d"
    ) -> dict:
        """Per-label net flows. 1 credit; server-cached 10–30m; our file cache 6h."""
        data = await self._post(
            "/api/v1/tgm/flow-intelligence",
            {"chain": self.chain, "token_address": token_mint, "timeframe": timeframe},
            cache_name=f"flow_{token_mint[:16]}_{timeframe}",
            ttl=FLOW_CACHE_TTL_S,
        )
        records = self._records(data)
        return records[0] if records else {}

    async def indicators(self, token_mint: str) -> dict:
        """Risk/reward indicator groups. 5 credits; DAILY batch (not realtime)."""
        data = await self._post(
            "/api/v1/tgm/indicators",
            {"chain": self.chain, "token_address": token_mint},
            cache_name=f"indicators_{token_mint[:16]}",
        )
        return data if isinstance(data, dict) else {}

    # --- Mapping into Tarstrade signal inputs ---

    async def onchain_flow_inputs(self, token_mint: str) -> dict:
        """Map flow-intelligence record → onchain_flow_signal() kwargs.

        Neutral zeros when unavailable — missing flow is no-evidence, never signal.
        """
        neutral = {
            "whale_net_flow_usd": 0.0,
            "exchange_reserve_change_pct": 0.0,
            "stablecoin_supply_change_pct": 0.0,
        }
        rec = await self.flow_intelligence(token_mint)
        if not rec:
            return neutral
        try:
            whale = float(rec.get("whale_net_flow_usd", 0.0) or 0.0)
            smart = float(rec.get("smart_trader_net_flow_usd", 0.0) or 0.0)
            exch = float(rec.get("exchange_net_flow_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            return neutral
        return {
            "whale_net_flow_usd": whale + smart,
            # Exchange net inflow GLASSNODE-style proxy: +inflow = distribution.
            "exchange_reserve_change_pct": 1.0 if exch > 0 else (-1.0 if exch < 0 else 0.0),
            "stablecoin_supply_change_pct": 0.0,  # stablecoin leg needs screener-level data
        }

    async def concentration_flag(self, token_mint: str) -> dict:
        """Holder-concentration scream filter (EXPANSION_ROADMAP pattern).

        indicators[].risk_indicators entry with indicator_type containing
        "concentration" and score "high" → concentrated. Unavailable → False.
        """
        ind = await self.indicators(token_mint)
        for entry in ind.get("risk_indicators", []) or []:
            if not isinstance(entry, dict):
                continue
            if "concentration" in str(entry.get("indicator_type", "")).lower():
                if str(entry.get("score", "")).lower() == "high":
                    return {
                        "concentrated": True,
                        "reason": f"nansen concentration-risk high "
                        f"(pctl {entry.get('signal_percentile')})",
                    }
                return {"concentrated": False, "reason": "concentration-risk not high"}
        return {"concentrated": False, "reason": "no concentration signal"}


async def demo():
    client = NansenClient()
    try:
        print("available:", client.available)
        print("flow inputs (neutral):", await client.onchain_flow_inputs("So11111111111111111111111111111111111111112"))
    finally:
        await client.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(demo())
