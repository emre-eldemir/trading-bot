"""
app/execution/order_manager.py — Order lifecycle management.

Tracks active orders, handles partial fills, timeouts, and cancellations.
Prevents duplicate orders for the same signal/opportunity.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.config import TradingConfig, get_settings
from app.execution.base_adapter import BaseAdapter
from app.models.trade import Order, OrderStatus
from app.utils.logging_config import Events, log_event

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Manages order lifecycle: submission, tracking, timeout, cancellation.

    Deduplication: tracks signal_id → order mapping to prevent sending
    multiple orders for the same opportunity.
    """

    def __init__(
        self,
        adapter: BaseAdapter,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._adapter = adapter
        self._settings = settings or get_settings()
        self._active_orders: dict[str, Order] = {}   # order_id → Order
        self._signal_orders: dict[str, str] = {}      # signal_id → order_id (dedup)

    async def submit(self, order: Order) -> Order:
        """
        Submit an order with deduplication and retry logic.

        Returns the submitted (and possibly filled) order.
        Raises RuntimeError if max retries exceeded.
        """
        # Deduplication: check if signal already has a live order
        if order.signal_id and order.signal_id in self._signal_orders:
            existing_id = self._signal_orders[order.signal_id]
            if existing_id in self._active_orders:
                logger.warning(
                    "Duplicate order for signal %s — already active order %s",
                    order.signal_id, existing_id,
                )
                return self._active_orders[existing_id]

        # Retry loop
        for attempt in range(self._settings.max_retries):
            try:
                submitted = await self._adapter.submit_order(order)
                self._active_orders[submitted.id] = submitted
                if order.signal_id:
                    self._signal_orders[order.signal_id] = submitted.id

                log_event(
                    logger, Events.ORDER_SUBMITTED,
                    order_id=submitted.id,
                    symbol=submitted.symbol,
                    side=submitted.side.value,
                    qty=submitted.quantity,
                    price=submitted.price,
                )
                return submitted

            except Exception as e:
                logger.warning("Order submission attempt %d failed: %s", attempt + 1, e)
                if attempt < self._settings.max_retries - 1:
                    await asyncio.sleep(self._settings.retry_delay)

        raise RuntimeError(f"Order submission failed after {self._settings.max_retries} retries")

    async def wait_for_fill(self, order: Order) -> Order:
        """
        Poll order status until filled, cancelled, or timeout.

        Returns the final order state.
        """
        start = datetime.utcnow()
        while True:
            elapsed = (datetime.utcnow() - start).total_seconds()
            if elapsed > self._settings.order_timeout:
                # Cancel timed-out order
                cancelled = await self.cancel(order)
                log_event(
                    logger, Events.ORDER_TIMEOUT,
                    order_id=order.id,
                    elapsed=f"{elapsed:.1f}s",
                )
                return cancelled

            updated = await self._adapter.get_order_status(order)
            self._active_orders[order.id] = updated

            if updated.status == OrderStatus.FILLED:
                log_event(
                    logger, Events.ORDER_FILLED,
                    order_id=updated.id,
                    fill_price=updated.average_fill_price,
                    qty=updated.filled_quantity,
                    fee=updated.fee_paid,
                )
                self._cleanup(order)
                return updated

            if updated.status == OrderStatus.PARTIALLY_FILLED:
                log_event(
                    logger, Events.PARTIAL_FILL,
                    order_id=updated.id,
                    filled=updated.filled_quantity,
                    remaining=updated.quantity - updated.filled_quantity,
                )

            if updated.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                self._cleanup(order)
                return updated

            await asyncio.sleep(0.5)

    async def cancel(self, order: Order) -> Order:
        """Cancel an active order."""
        try:
            cancelled = await self._adapter.cancel_order(order)
            log_event(logger, Events.ORDER_CANCELLED, order_id=order.id)
            self._cleanup(order)
            return cancelled
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order.id, e)
            return order

    async def cancel_all(self) -> list[Order]:
        """Cancel all active orders (used during shutdown / kill switch)."""
        results = []
        for order in list(self._active_orders.values()):
            if order.status in (OrderStatus.OPEN, OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
                cancelled = await self.cancel(order)
                results.append(cancelled)
        return results

    def _cleanup(self, order: Order) -> None:
        """Remove order from active tracking."""
        self._active_orders.pop(order.id, None)
        if order.signal_id:
            self._signal_orders.pop(order.signal_id, None)

    @property
    def active_order_count(self) -> int:
        return len(self._active_orders)
