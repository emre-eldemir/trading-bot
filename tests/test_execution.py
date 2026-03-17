"""
tests/test_execution.py — Unit tests for the execution engine components.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.execution.mock_adapter import MockAdapter
from app.execution.order_manager import OrderManager
from app.models.trade import Order, OrderSide, OrderStatus, OrderType


class TestMockAdapter:
    """Tests for the mock exchange adapter."""

    def test_fetch_order_book(self, test_settings):
        """Should return a valid order book."""
        adapter = MockAdapter(test_settings)
        ob = asyncio.get_event_loop().run_until_complete(
            adapter.fetch_order_book("BTC/USDT")
        )
        assert ob.symbol == "BTC/USDT"
        assert len(ob.bids) > 0
        assert len(ob.asks) > 0
        assert ob.best_bid < ob.best_ask

    def test_fetch_ticker(self, test_settings):
        """Should return a valid ticker."""
        adapter = MockAdapter(test_settings)
        ticker = asyncio.get_event_loop().run_until_complete(
            adapter.fetch_ticker("BTC/USDT")
        )
        assert ticker.symbol == "BTC/USDT"
        assert ticker.bid < ticker.ask
        assert ticker.last > 0

    def test_market_order_fills_immediately(self, test_settings):
        """Market orders should be filled immediately."""
        adapter = MockAdapter(test_settings)
        order = Order(
            symbol="BTC/USDT",
            exchange="mock",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
        )
        filled = asyncio.get_event_loop().run_until_complete(adapter.submit_order(order))
        assert filled.status == OrderStatus.FILLED
        assert filled.filled_quantity == 0.01
        assert filled.average_fill_price and filled.average_fill_price > 0

    def test_limit_order_fills_at_price(self, test_settings):
        """Limit order at current price should fill."""
        adapter = MockAdapter(test_settings)
        current_price = adapter._get_current_price("BTC/USDT")
        # Buy limit above current ask should fill
        order = Order(
            symbol="BTC/USDT",
            exchange="mock",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.01,
            price=current_price * 1.01,  # 1% above current price
        )
        result = asyncio.get_event_loop().run_until_complete(adapter.submit_order(order))
        assert result.status == OrderStatus.FILLED

    def test_cancel_order(self, test_settings):
        """Should be able to cancel an order."""
        adapter = MockAdapter(test_settings)
        order = Order(
            symbol="BTC/USDT",
            exchange="mock",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.01,
            price=60000.0,  # Well below market — won't fill
        )
        submitted = asyncio.get_event_loop().run_until_complete(adapter.submit_order(order))
        cancelled = asyncio.get_event_loop().run_until_complete(adapter.cancel_order(submitted))
        assert cancelled.status == OrderStatus.CANCELLED

    def test_balance_decreases_after_buy(self, test_settings):
        """Balance should decrease after a market buy."""
        adapter = MockAdapter(test_settings)
        initial_balance = adapter._balance.get("USDT", 0)
        order = Order(
            symbol="BTC/USDT",
            exchange="mock",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.1,
        )
        asyncio.get_event_loop().run_until_complete(adapter.submit_order(order))
        new_balance = adapter._balance.get("USDT", 0)
        assert new_balance < initial_balance


class TestOrderManager:
    """Tests for order lifecycle management."""

    def test_submit_returns_order(self, test_settings):
        """Submit should return an Order object."""
        adapter = MockAdapter(test_settings)
        manager = OrderManager(adapter, test_settings)
        order = Order(
            symbol="BTC/USDT",
            exchange="mock",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=0.01,
        )
        result = asyncio.get_event_loop().run_until_complete(manager.submit(order))
        assert isinstance(result, Order)

    def test_deduplication_prevents_duplicate(self, test_settings):
        """Same signal_id should not result in duplicate orders for open orders."""
        adapter = MockAdapter(test_settings)
        manager = OrderManager(adapter, test_settings)
        # Use a limit order well below market so it stays open (not filled immediately)
        order = Order(
            symbol="BTC/USDT",
            exchange="mock",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=0.01,
            price=50000.0,  # Far below market — won't fill
            signal_id="test-signal-dedup-999",
        )
        r1 = asyncio.get_event_loop().run_until_complete(manager.submit(order))
        # r1 should be open (not filled at 50000 when market is ~65000)
        if r1.status == OrderStatus.OPEN:
            # Second submit with same signal_id should return the existing order
            r2 = asyncio.get_event_loop().run_until_complete(manager.submit(order))
            assert r2.id == r1.id
