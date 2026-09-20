"""Bitget public-data adapter — read-only second opinion, no account, no key.

Docs (probed 2026-09-20; shapes below are live responses):
  UTA v3 tickers: GET /api/v3/market/tickers?category=SPOT&symbol=<SYM>
  -> {"code": "00000", "data": [{"symbol", "ts" (ms), "lastPrice",
      "bid1Price", "ask1Price", ...}]}. Rate limit 20/sec/IP. No auth.
  Reality guide (https://www.bitget.com/api-doc/uta/reality-trading-guide):
  rTokens are r-prefixed (rAAPLUSDT), tickers reuse the public endpoint.
  S1-era ONUSDT symbols are dead ("does not exist") — do not use them.

Role in Stockulus (venue rule: venues plug in, execution stays Solana):
  - get_spot(symbol): independent cross-check for xStocks spot in the
    data-integrity divergence guard. Missing/failed -> documented neutral,
    never a block by itself.
  - get_sol_usd(): tier-2 fallback in the SOL conversion chain
    (pyth.Hermes -> bitget -> SOL_PRICE_USD env -> 150.0).

Verified live 2026-09-20: rAAPL 335.1 / rTSLA 363.84 / rNVDA 221.04
vs xStocks 337.24 / 366.47 / 219.72 — same underlyings, real venue spread.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE = "https://api.bitget.com"
CATEGORY = "SPOT"
TIMEOUT = 20.0
CACHE_TTL_S = 60.0

# xStocks suffix-x -> Bitget rToken (r-prefixed per Reality guide).
SYMBOL_MAP = {
    "AAPLx": "rAAPLUSDT",
    "TSLAx": "rTSLAUSDT",
    "NVDAx": "rNVDAUSDT",
}
SOL_SYMBOL = "SOLUSDT"


class BitgetClient:
    """Keyless public-data client with TTL cache. Failures -> neutrals."""

    def __init__(self, base: str = BASE, timeout: float = TIMEOUT):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, dict[str, Any]] = {}

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ticker(self, symbol: str) -> dict[str, Any] | None:
        now = time.time()
        hit = self._cache.get(symbol)
        if hit and now - hit.get("at", 0) < CACHE_TTL_S:
            return hit["quote"]
        try:
            if self._client is None:
                self._client = httpx.AsyncClient(timeout=self.timeout)
            resp = await self._client.get(
                f"{self.base}/api/v3/market/tickers",
                params={"category": CATEGORY, "symbol": symbol},
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") != "00000" or not body.get("data"):
                return None
            node = body["data"][0]
            quote = {
                "symbol": node.get("symbol", symbol),
                "price": float(node["lastPrice"]),
                "bid": float(node.get("bid1Price") or 0),
                "ask": float(node.get("ask1Price") or 0),
                "ts": int(node.get("ts") or 0),
                "source": "bitget-rtoken",
            }
            self._cache[symbol] = {"at": now, "quote": quote}
            return quote
        except Exception as e:  # noqa: BLE001 — public feed, fail soft
            logger.debug(f"Bitget ticker {symbol} failed: {e}")
            return None

    async def get_spot(self, asset: str) -> dict[str, Any]:
        """Cross-check quote for an xStocks symbol. Neutral when unavailable."""
        symbol = SYMBOL_MAP.get(asset)
        if symbol is None:
            logger.debug(f"Bitget: no rToken mapping for {asset}")
            return {"price": None, "source": "bitget-unmapped"}
        quote = await self._ticker(symbol)
        if quote is None:
            return {"price": None, "source": "bitget-unavailable"}
        return quote

    async def get_sol_usd(self) -> dict[str, Any]:
        """SOL/USD from public spot ticker. Neutral when unavailable."""
        quote = await self._ticker(SOL_SYMBOL)
        if quote is None:
            return {"available": False, "source": "bitget-unavailable"}
        quote["source"] = "bitget-spot"
        return {"available": True, **quote}
