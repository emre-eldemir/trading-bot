"""
app/execution/mock_adapter.py — Mock exchange adapter for development/paper trading.

Simulates realistic order fills using sample order book data.
Supports: instant fills for market orders, price-conditional fills for limit orders.
Includes realistic slippage and fee simulation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import TradingConfig, get_settings
from app.execution.base_adapter import BaseAdapter
from app.models.market import OrderBook, OrderBookLevel, Ticker
from app.models.trade import Order, OrderSide, OrderStatus, OrderType

logger = logging.getLogger(__name__)

# Path to sample data files
_DATA_DIR = Path(__file__).parent.parent.parent / "data"


class MockAdapter(BaseAdapter):
    """
    Simulated exchange adapter using mock/sample data.

    Features:
    - Generates realistic order book data (or loads from sample files)
    - Simulates market order fills with slippage
    - Simulates limit order fills based on price conditions
    - Tracks simulated balance
    """

    def __init__(self, settings: Optional[TradingConfig] = None) -> None:
        self._settings = settings or get_settings()
        self._balance: dict[str, float] = {
            "USDT": self._settings.starting_bankroll,
            "BTC": 0.0,
            "ETH": 0.0,
            "SOL": 0.0,
        }
        self._pending_orders: dict[str, Order] = {}
        # Base prices for simulation
        self._base_prices: dict[str, float] = {
            "BTC/USDT": 65000.0,
            "ETH/USDT": 3500.0,
            "SOL/USDT": 180.0,
        }
        self._price_drift: dict[str, float] = {k: 0.0 for k in self._base_prices}

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        """
        Return a simulated order book with realistic spread and depth.
        Adds small random price noise to simulate live market conditions.
        """
        await asyncio.sleep(0)  # Allow event loop to breathe

        # Try loading from sample file first
        sample_book = self._load_sample_order_book(symbol)
        if sample_book:
            return sample_book

        # Generate synthetic order book
        base_price = self._get_current_price(symbol)
        spread_pct = 0.0005 + random.uniform(0, 0.0010)  # 0.05% to 0.15% spread
        half_spread = base_price * spread_pct / 2

        bids: list[OrderBookLevel] = []
        asks: list[OrderBookLevel] = []

        for i in range(depth):
            bid_price = base_price - half_spread - i * base_price * 0.0002
            ask_price = base_price + half_spread + i * base_price * 0.0002
            size = random.uniform(0.1, 5.0)
            bids.append(OrderBookLevel(price=round(bid_price, 2), size=round(size, 4)))
            asks.append(OrderBookLevel(price=round(ask_price, 2), size=round(size, 4)))

        return OrderBook(
            symbol=symbol,
            exchange="mock",
            timestamp=datetime.utcnow(),
            bids=bids,
            asks=asks,
        )

    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Return a simulated ticker."""
        await asyncio.sleep(0)

        price = self._get_current_price(symbol)
        spread = price * 0.0005
        change = random.uniform(-0.02, 0.02)

        return Ticker(
            symbol=symbol,
            exchange="mock",
            timestamp=datetime.utcnow(),
            bid=round(price - spread / 2, 2),
            ask=round(price + spread / 2, 2),
            last=round(price, 2),
            volume_24h=round(random.uniform(1000, 50000), 2),
            price_change_24h=round(change, 4),
            high_24h=round(price * (1 + abs(change) * 2), 2),
            low_24h=round(price * (1 - abs(change) * 2), 2),
        )

    async def submit_order(self, order: Order) -> Order:
        """
        Simulate order submission.

        Market orders: fill immediately at best price + slippage.
        Limit orders: fill if price condition is met.
        """
        await asyncio.sleep(random.uniform(0.01, 0.05))  # Simulate network latency

        exchange_id = str(uuid.uuid4())[:8]
        current_price = self._get_current_price(order.symbol)
        updated = order.model_copy(update={
            "exchange_order_id": exchange_id,
            "updated_at": datetime.utcnow(),
        })

        if order.order_type == OrderType.MARKET:
            updated = await self._fill_market_order(updated, current_price)

        elif order.order_type in (OrderType.LIMIT, OrderType.POST_ONLY):
            updated = await self._try_fill_limit_order(updated, current_price)

        if updated.status != OrderStatus.FILLED:
            self._pending_orders[exchange_id] = updated

        return updated

    async def cancel_order(self, order: Order) -> Order:
        """Cancel a pending order."""
        self._pending_orders.pop(order.exchange_order_id, None)
        return order.model_copy(update={
            "status": OrderStatus.CANCELLED,
            "cancelled_at": datetime.utcnow(),
        })

    async def get_order_status(self, order: Order) -> Order:
        """Check if a pending limit order has been filled."""
        if order.exchange_order_id not in self._pending_orders:
            return order  # Already filled or cancelled

        current_price = self._get_current_price(order.symbol)
        pending = self._pending_orders[order.exchange_order_id]
        updated = await self._try_fill_limit_order(pending, current_price)

        if updated.status == OrderStatus.FILLED:
            self._pending_orders.pop(order.exchange_order_id, None)

        return updated

    async def get_balance(self) -> dict[str, float]:
        """Return simulated balance."""
        return dict(self._balance)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_current_price(self, symbol: str) -> float:
        """Get current simulated price with small random walk."""
        if symbol not in self._base_prices:
            self._base_prices[symbol] = 100.0

        # Small random walk to simulate price movement
        drift = random.gauss(0, 0.0005)
        self._price_drift[symbol] = self._price_drift.get(symbol, 0.0) + drift
        # Cap drift to ±5%
        self._price_drift[symbol] = max(-0.05, min(0.05, self._price_drift[symbol]))

        return self._base_prices[symbol] * (1 + self._price_drift[symbol])

    async def _fill_market_order(self, order: Order, current_price: float) -> Order:
        """Fill a market order with slippage."""
        slippage = random.uniform(0.0001, 0.001)  # 0.01% to 0.1% slippage
        if order.side == OrderSide.BUY:
            fill_price = current_price * (1 + slippage)
        else:
            fill_price = current_price * (1 - slippage)

        fee = order.quantity * fill_price * self._settings.taker_fee
        self._update_balance(order, fill_price)

        return order.model_copy(update={
            "status": OrderStatus.FILLED,
            "filled_quantity": order.quantity,
            "average_fill_price": round(fill_price, 6),
            "fee_paid": round(fee, 6),
            "filled_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })

    async def _try_fill_limit_order(self, order: Order, current_price: float) -> Order:
        """Try to fill a limit order based on price condition."""
        if order.price is None:
            return order

        filled = False
        if order.side == OrderSide.BUY and current_price <= order.price:
            filled = True
        elif order.side == OrderSide.SELL and current_price >= order.price:
            filled = True

        if filled:
            fee = order.quantity * order.price * self._settings.maker_fee
            self._update_balance(order, order.price)
            return order.model_copy(update={
                "status": OrderStatus.FILLED,
                "filled_quantity": order.quantity,
                "average_fill_price": order.price,
                "fee_paid": round(fee, 6),
                "filled_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            })

        return order.model_copy(update={"status": OrderStatus.OPEN})

    def _update_balance(self, order: Order, fill_price: float) -> None:
        """Update simulated balance after fill."""
        base_currency = order.symbol.split("/")[0]
        quote_currency = order.symbol.split("/")[1] if "/" in order.symbol else "USDT"
        trade_value = order.quantity * fill_price

        if order.side == OrderSide.BUY:
            self._balance[quote_currency] = self._balance.get(quote_currency, 0) - trade_value
            self._balance[base_currency] = self._balance.get(base_currency, 0) + order.quantity
        else:
            self._balance[base_currency] = self._balance.get(base_currency, 0) - order.quantity
            self._balance[quote_currency] = self._balance.get(quote_currency, 0) + trade_value

    def _load_sample_order_book(self, symbol: str) -> Optional[OrderBook]:
        """Load sample order book from data directory if available."""
        try:
            sample_file = _DATA_DIR / "sample_orderbook.json"
            if not sample_file.exists():
                return None
            with open(sample_file) as f:
                data = json.load(f)
            # Find matching symbol
            for entry in data:
                if entry.get("symbol") == symbol:
                    bids = [OrderBookLevel(**lvl) for lvl in entry.get("bids", [])]
                    asks = [OrderBookLevel(**lvl) for lvl in entry.get("asks", [])]
                    return OrderBook(
                        symbol=symbol,
                        exchange="mock",
                        bids=bids,
                        asks=asks,
                    )
        except Exception:
            pass
        return None
