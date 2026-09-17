"""
Order executor: routes to Meteora DBC via TS SDK subprocess after the
RiskGate has approved an order. The execution layer is dumb — it routes orders;
the risk gate decides.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from .models import (
    OrderRequest,
    OrderResult,
    OrderStatus,
    ExecutionError,
)
from ..meteora_executor import MeteoraExecutor, SwapResult

logger = logging.getLogger(__name__)


class OrderExecutor:
    """
    Safe order executor that wraps the Meteora DBC SDK via subprocess with
    pre-trade risk checks.

    Architecture:
      TradingAgent → RiskGate.check(order) → OrderExecutor.place(order)

    The RiskGate is non-overridable — if it rejects, the order never reaches DBC.
    """

    def __init__(
        self,
        meteora_executor: MeteoraExecutor,
        risk_gate,
        dry_run: bool = False,
        agent_id: str = "default",
        fill_poll_attempts: int = 3,
        fill_poll_delay: float = 0.5,
    ):
        self.meteora = meteora_executor
        self.risk_gate = risk_gate
        self.dry_run = dry_run
        self.agent_id = agent_id
        self.fill_poll_attempts = fill_poll_attempts
        self.fill_poll_delay = fill_poll_delay

    async def place_order(
        self,
        order: OrderRequest,
        current_price: float | None = None,
        current_price_timestamp: float | None = None,
    ) -> OrderResult:
        """
        Place an order after passing risk checks.
        In dry-run mode, simulates the order without sending to DBC.
        """
        # --- Step 1: Risk gate check (non-overridable) ---
        current_position_side = None  # Would fetch from vault/position tracking
        risk_check = self.risk_gate.check_order(
            order,
            agent_id=self.agent_id,
            current_price=current_price,
            current_price_timestamp=current_price_timestamp,
            current_position_side=current_position_side,
            unwind=order.unwind,
            count_trade=not self.dry_run,
        )
        if not risk_check.approved:
            raise ExecutionError(
                f"Risk gate rejected order: {risk_check.reason}. Code: {risk_check.code}"
            )

        if self.dry_run:
            result = OrderResult(
                order_id=f"dryrun_{uuid.uuid4().hex[:8]}",
                client_oid=order.client_oid or "",
                state=OrderStatus.FILLED,
                acc_fill_sz=order.size,
                fill_px=order.px or "0",
                fill_sz=order.size,
                fill_usd=order.size,
                fee="0",
                fee_ccy="USDC",
                error=None,
                raw={"dry_run": True, **order.to_dict()},
            )
            return self._verify_fill(order, result, reference_price=current_price)

        # --- Step 2: Submit to Meteora DBC via TS SDK ---
        # order.inst_id is the pool pubkey for DBC
        # order.size is in USDC (quote currency)
        try:
            swap_result = self.meteora.swap(
                pool=order.inst_id,
                amount_in=float(order.size),
                min_out=float(order.size) * 0.99,  # 1% slippage tolerance default
                swap_base_for_quote=(order.side == "sell"),  # sell base = swap base for quote
            )
        except Exception as e:
            raise ExecutionError(f"Meteora DBC swap failed: {e}") from e

        order_result = OrderResult(
            order_id=swap_result.tx,
            client_oid=order.client_oid or "",
            state=OrderStatus.FILLED,
            acc_fill_sz=str(swap_result.out_amount),
            fill_px=str(current_price or 0),
            fill_sz=str(swap_result.out_amount),
            fill_usd=str(swap_result.out_amount),
            fee=str(swap_result.fee),
            fee_ccy="USDC",
            raw={"tx": swap_result.tx, "price_impact": swap_result.price_impact},
        )
        return self._verify_fill(order, order_result, reference_price=current_price)

    def _verify_fill(self, order: OrderRequest, result: OrderResult,
                     reference_price: float | None) -> OrderResult:
        """Post-fill slippage verification."""
        if reference_price is None or reference_price <= 0:
            result.fill_verified = None
            return result
        try:
            fill_px = float(result.fill_px) if result.fill_px is not None else 0.0
        except (TypeError, ValueError):
            fill_px = 0.0
        if fill_px <= 0:
            result.fill_verified = None
            return result

        slippage_pct = abs(fill_px - reference_price) / reference_price * 100.0
        result.slippage_pct = round(slippage_pct, 4)

        collar = self.risk_gate.max_slippage_pct
        hard_collar = collar * 2.0
        if slippage_pct <= collar:
            result.fill_verified = True
        elif slippage_pct <= hard_collar:
            result.fill_verified = False
            result.error = (
                f"Post-fill slippage {slippage_pct:.2f}% vs reference "
                f"{reference_price} exceeds {collar:.2f}% collar (fill {fill_px}). "
                f"Order {order.client_oid} filled on poor terms."
            )
        else:
            result.fill_verified = False
            result.error = (
                f"Post-fill slippage {slippage_pct:.2f}% vs reference "
                f"{reference_price} exceeds hard collar {hard_collar:.2f}% "
                f"(fill {fill_px}). Tripping kill switch — fills are untrustworthy."
            )
            self.risk_gate.activate_kill_switch(reason=result.error)
        return result

    async def get_order_status(self, order_id: str, pool: str) -> OrderResult:
        """Query status - for DBC, check tx on explorer or re-query pool state."""
        # Simplified: assume filled if tx exists
        return OrderResult(
            order_id=order_id,
            client_oid="",
            state=OrderStatus.FILLED,
            acc_fill_sz="0",
            fill_px=None,
            fill_sz=None,
            fill_usd=None,
            fee="0",
            fee_ccy="USDC",
        )

    async def cancel_order(self, order_id: str, pool: str) -> bool:
        """Cancel not directly supported on DBC — would need to unwind position."""
        if self.dry_run:
            return True
        logger.warning("DBC order cancellation not directly supported; use unwind")
        return False

    async def amend_order(self, order_id: str, pool: str, **kwargs) -> dict:
        if self.dry_run:
            return {"dry_run": True}
        raise NotImplementedError("Amend not supported on DBC")

    async def get_position(self, pool: str) -> dict | None:
        """Get current position from pool state."""
        try:
            state = self.meteora.get_pool_state(pool)
            return {
                "base_reserve": state.get("baseReserve", 0),
                "quote_reserve": state.get("quoteReserve", 0),
                "sqrt_price": state.get("sqrtPrice", 0),
            }
        except Exception:
            return None