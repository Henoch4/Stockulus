"""
Clawpump API client — thin wrapper for agent launch + token launch + earnings.
Devnet works per Discord confirmation. Requires cpk_ API key from dashboard.
"""
from __future__ import annotations

import httpx
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

BASE = "https://clawpump.tech/api"


@dataclass
class LaunchResult:
    mint: str
    pool: str
    tx: str


class ClawpumpClient:
    """Clawpump API wrapper for agent/token operations."""

    def __init__(self, api_key: str, base: str = BASE, timeout: float = 30.0):
        if not api_key.startswith("cpk_"):
            raise ValueError("API key must start with cpk_")
        self.api_key = api_key
        self.base = base
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    async def close(self):
        await self._client.aclose()

    # --- Agent lifecycle ---

    async def create_agent(self, name: str, persona: str = "", model: str = "gpt-4o") -> dict[str, Any]:
        """POST /api/v1/agents — create agent with wallet."""
        resp = await self._client.post(
            f"{self.base}/v1/agents",
            json={"name": name, "persona": persona, "model": model},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """GET /api/v1/agents/{id} — agent details + wallet."""
        resp = await self._client.get(f"{self.base}/v1/agents/{agent_id}")
        resp.raise_for_status()
        return resp.json()

    async def list_agents(self) -> list[dict]:
        """GET /api/v1/agents — list all agents."""
        resp = await self._client.get(f"{self.base}/v1/agents")
        resp.raise_for_status()
        return resp.json()

    # --- Token launch ---

    async def launch_token(
        self,
        agent_id: str,
        name: str,
        ticker: str,
        quote_mint: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        meteora_config_pubkey: str | None = None,
    ) -> LaunchResult:
        """POST /api/v1/launch — paid launch from agent wallet.
        Requires: agent has USDC balance, cpk_ key has launch permission.
        """
        payload = {
            "agent_id": agent_id,
            "name": name,
            "ticker": ticker,
            "quote_mint": quote_mint,
        }
        if meteora_config_pubkey:
            payload["meteora_config"] = meteora_config_pubkey

        resp = await self._client.post(f"{self.base}/v1/launch", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return LaunchResult(
            mint=data.get("mint", ""),
            pool=data.get("pool", ""),
            tx=data.get("tx", ""),
        )

    async def get_launch_status(self, agent_id: str) -> dict:
        """GET /api/v1/launch/status — readiness check."""
        resp = await self._client.get(f"{self.base}/v1/launch/status", params={"agent_id": agent_id})
        resp.raise_for_status()
        return resp.json()

    # --- Earnings ---

    async def get_earnings(self, agent_id: str) -> dict:
        """GET /api/agents/{id}/earnings — creator fees (75% eligible)."""
        resp = await self._client.get(f"{self.base}/agents/{agent_id}/earnings")
        resp.raise_for_status()
        return resp.json()

    # --- Trading (via agent) ---

    async def swap_quote(self, input_mint: str, output_mint: str, amount: float) -> dict:
        """GET /api/v1/swap/quote — best price across Jupiter/OKX."""
        resp = await self._client.get(
            f"{self.base}/v1/swap/quote",
            params={"input_mint": input_mint, "output_mint": output_mint, "amount": str(amount)},
        )
        resp.raise_for_status()
        return resp.json()

    async def swap_execute(self, agent_id: str, input_mint: str, output_mint: str, amount: float) -> dict:
        """POST /api/v1/swap/execute — execute swap via agent wallet."""
        resp = await self._client.post(
            f"{self.base}/v1/swap/execute",
            json={"agent_id": agent_id, "input_mint": input_mint, "output_mint": output_mint, "amount": str(amount)},
        )
        resp.raise_for_status()
        return resp.json()

    # --- Agent wallet ---

    async def get_wallet_balance(self, agent_id: str) -> dict:
        """GET /api/agents/{id}/balance — SOL/USDC balance."""
        resp = await self._client.get(f"{self.base}/agents/{agent_id}/balance")
        resp.raise_for_status()
        return resp.json()

    async def get_wallet_summary(self) -> dict:
        """GET /api/v1/wallet/summaries — all agent balances."""
        resp = await self._client.get(f"{self.base}/v1/wallet/summaries")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()


async def demo():
    """Test with cpk_ key from env."""
    import os
    api_key = os.getenv("CLAWPUMP_API_KEY")
    if not api_key:
        print("Set CLAWPUMP_API_KEY env var (cpk_...)")
        return
    client = ClawpumpClient(api_key)
    try:
        agents = await client.list_agents()
        print(f"Agents: {len(agents)}")
        if agents:
            aid = agents[0]["id"]
            earnings = await client.get_earnings(aid)
            print(f"Earnings: {earnings}")
    finally:
        await client.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(demo())