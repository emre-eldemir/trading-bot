"""
tests/test_market_scanner.py — Unit tests for the Market Scanner.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.market import MarketMetrics, OrderBook, OrderBookLevel, Ticker
from app.services.market_scanner import MarketScanner


@pytest.fixture
def mock_adapter():
    """Mock exchange adapter that returns sample data."""
    adapter = AsyncMock()
    adapter.fetch_order_book.return_value = OrderBook(
        symbol="BTC/USDT",
        exchange="mock",
        bids=[
            OrderBookLevel(price=64990.0, size=1.0),
            OrderBookLevel(price=64985.0, size=2.0),
            OrderBookLevel(price=64980.0, size=3.0),
        ],
        asks=[
            OrderBookLevel(price=65010.0, size=0.8),
            OrderBookLevel(price=65015.0, size=1.5),
            OrderBookLevel(price=65020.0, size=2.2),
        ],
    )
    adapter.fetch_ticker.return_value = Ticker(
        symbol="BTC/USDT",
        exchange="mock",
        bid=64990.0,
        ask=65010.0,
        last=65000.0,
        volume_24h=5000.0,
    )
    return adapter


class TestMarketScanner:
    """Tests for MarketScanner."""

    def test_scanner_initialises(self, mock_adapter, test_settings):
        """Scanner should initialise without error."""
        scanner = MarketScanner(mock_adapter, test_settings)
        assert scanner is not None

    def test_scanner_registers_callback(self, mock_adapter, test_settings):
        """Callbacks should be registered correctly."""
        scanner = MarketScanner(mock_adapter, test_settings)
        cb = MagicMock()
        scanner.register_callback(cb)
        assert cb in scanner._callbacks

    def test_scan_symbol_returns_metrics(self, mock_adapter, test_settings):
        """Scanning a symbol should return valid MarketMetrics."""
        scanner = MarketScanner(mock_adapter, test_settings)
        result = asyncio.get_event_loop().run_until_complete(
            scanner._scan_symbol("BTC/USDT")
        )
        assert isinstance(result, MarketMetrics)
        assert result.symbol == "BTC/USDT"
        assert result.mid_price > 0
        assert result.spread >= 0

    def test_order_book_properties(self, sample_order_book):
        """OrderBook computed properties should be correct."""
        ob = sample_order_book
        assert ob.best_bid == 64990.0
        assert ob.best_ask == 65010.0
        assert ob.mid_price == 65000.0
        assert ob.spread == 20.0
        assert ob.spread_pct > 0

    def test_order_book_imbalance(self):
        """Imbalance should be in [-1, 1]."""
        ob = OrderBook(
            symbol="BTC/USDT",
            exchange="mock",
            bids=[OrderBookLevel(price=100.0, size=10.0)],
            asks=[OrderBookLevel(price=101.0, size=5.0)],
        )
        imbalance = ob.imbalance()
        assert -1.0 <= imbalance <= 1.0
        # More bids than asks → positive imbalance
        assert imbalance > 0

    def test_latest_metrics_stored(self, mock_adapter, test_settings):
        """Latest metrics should be stored after scan."""
        scanner = MarketScanner(mock_adapter, test_settings)
        asyncio.get_event_loop().run_until_complete(scanner._scan_all_symbols())
        metrics = scanner.get_latest_metrics("BTC/USDT")
        assert metrics is not None

    def test_get_all_metrics(self, mock_adapter, test_settings):
        """get_all_metrics should return dict of all scanned symbols."""
        scanner = MarketScanner(mock_adapter, test_settings)
        asyncio.get_event_loop().run_until_complete(scanner._scan_all_symbols())
        all_m = scanner.get_all_metrics()
        assert isinstance(all_m, dict)
