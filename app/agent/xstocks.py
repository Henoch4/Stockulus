"""xStocks API adapter — public endpoints only, no auth needed for demo."""
from __future__ import annotations

import httpx
from typing import Any

BASE = "https://api.xstocks.fi/api/v2"
TIMEOUT = 20.0


class XStocksClient:
    def __init__(self, base: str = BASE, timeout: float = TIMEOUT):
        self.base = base
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
        self._cache: dict[str, Any] = {}

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str) -> Any:
        url = f"{self.base}{path}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.json()

    # --- Public endpoints ---

    async def list_assets(self) -> list[dict]:
        """GET /public/assets — all tokenized assets with Solana mints."""
        if "assets" not in self._cache:
            self._cache["assets"] = await self._get("/public/assets")
        return self._cache["assets"]

    async def get_asset(self, symbol: str) -> dict:
        """GET /public/assets/{symbol} — full details for one asset."""
        return await self._get(f"/public/assets/{symbol}")

    async def get_price(self, symbol: str) -> dict:
        """GET /public/assets/{symbol}/price-data — {price, source: onchain|nasdaq-blueocean}."""
        return await self._get(f"/public/assets/{symbol}/price-data")

    async def get_multiplier(self, symbol: str) -> dict:
        """GET /public/assets/{symbol}/multiplier — {current, pending} for display = raw * mult."""
        return await self._get(f"/public/assets/{symbol}/multiplier")

    async def get_multiplier_history(self, symbol: str) -> dict:
        """GET /public/assets/{symbol}/multiplier/history — splits/divs."""
        return await self._get(f"/public/assets/{symbol}/multiplier/history")

    async def get_upcoming_corporate_actions(self) -> dict:
        """GET /public/corporate-actions/upcoming — earnings/div calendar for blackout."""
        return await self._get("/public/corporate-actions/upcoming")

    async def get_oracles(self, symbol: str) -> dict:
        """GET /public/oracles/{symbol} — oracle PDAs per network."""
        return await self._get(f"/public/oracles/{symbol}")

    async def get_proof_of_reserves(self, symbol: str) -> dict:
        """GET /public/proof-of-reserves/{symbol} — backing check for dashboard."""
        return await self._get(f"/public/proof-of-reserves/{symbol}")

    # --- Helpers for our agent ---

    async def get_spot_price(self, symbol: str) -> float:
        """Fetch spot price and apply multiplier for display."""
        data = await self.get_price(symbol)
        price = float(data.get("price", 0))
        mult_data = await self.get_multiplier(symbol)
        mult = float(mult_data.get("current", 1.0))
        return price * mult

    async def get_solana_mint(self, symbol: str) -> str | None:
        """Extract Solana mint from asset details."""
        asset = await self.get_asset(symbol)
        chains = asset.get("chains", {})
        solana = chains.get("solana", {})
        return solana.get("mint")

    async def get_corporate_action_blackout(self, hours_ahead: int = 24) -> dict[str, float]:
        """Return {symbol: action_timestamp} for actions within hours_ahead."""
        actions = await self.get_upcoming_corporate_actions()
        blackout = {}
        import time
        now = time.time()
        cutoff = now + hours_ahead * 3600
        for action in actions.get("data", []):
            ts = float(action.get("timestamp", 0))
            if now < ts < cutoff:
                blackout[action.get("symbol", "")] = ts
        return blackout


async def demo():
    client = XStocksClient()
    try:
        assets = await client.list_assets()
        print(f"Found {len(assets)} assets")
        for a in assets[:5]:
            print(f"  {a.get('symbol')}: {a.get('name')}")
        if assets:
            sym = assets[0].get("symbol")
            price = await client.get_spot_price(sym)
            mint = await client.get_solana_mint(sym)
            print(f"{sym} spot={price} mint={mint}")
    finally:
        await client.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(demo())