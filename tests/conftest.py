"""
tests/conftest.py — Pytest fixtures shared across all test modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generator

import pytest

from app.config import TradingConfig
from app.models.market import MarketMetrics, OrderBook, OrderBookLevel, Ticker
from app.models.signal import Signal, SignalDirection, SignalType
from app.models.trade import Trade
from app.models.position import Position, PositionSide
from app.services.bankroll_manager import BankrollManager


@pytest.fixture
def test_settings() -> TradingConfig:
    """Test settings with safe defaults."""
    return TradingConfig(
        simulation_mode=True,
        live_trading=False,
        starting_bankroll=10000.0,
        kelly_fraction=0.25,
        min_edge=0.005,
        min_ev=0.001,
        maker_fee=0.0002,
        taker_fee=0.0005,
        signal_decay_half_life=60.0,
        daily_max_loss=0.02,
        max_drawdown=0.15,
        max_open_positions=5,
        max_single_trade_risk=0.02,
        min_confidence=0.5,
    )


@pytest.fixture
def sample_order_book() -> OrderBook:
    """Sample BTC/USDT order book."""
    return OrderBook(
        symbol="BTC/USDT",
        exchange="mock",
        bids=[
            OrderBookLevel(price=64990.0, size=0.5),
            OrderBookLevel(price=64985.0, size=1.0),
            OrderBookLevel(price=64980.0, size=2.0),
            OrderBookLevel(price=64975.0, size=3.0),
            OrderBookLevel(price=64970.0, size=5.0),
        ],
        asks=[
            OrderBookLevel(price=65010.0, size=0.4),
            OrderBookLevel(price=65015.0, size=0.8),
            OrderBookLevel(price=65020.0, size=1.5),
            OrderBookLevel(price=65025.0, size=2.5),
            OrderBookLevel(price=65030.0, size=4.0),
        ],
    )


@pytest.fixture
def sample_metrics() -> MarketMetrics:
    """Sample market metrics for BTC/USDT."""
    return MarketMetrics(
        symbol="BTC/USDT",
        exchange="mock",
        mid_price=65000.0,
        best_bid=64990.0,
        best_ask=65010.0,
        spread=20.0,
        spread_pct=0.000308,
        bid_depth=11.5,
        ask_depth=9.2,
        order_book_imbalance=0.11,
        estimated_slippage_buy=0.0003,
        estimated_slippage_sell=0.0003,
        volume_24h=5000.0,
        volatility=0.30,
        effective_spread_with_taker=0.001308,
    )


@pytest.fixture
def sample_signal() -> Signal:
    """Sample BUY signal with positive edge."""
    return Signal(
        strategy="mispricing",
        signal_type=SignalType.MISPRICING,
        symbol="BTC/USDT",
        exchange="mock",
        direction=SignalDirection.BUY,
        entry_price=65010.0,
        fair_value=65200.0,
        raw_edge=0.029,
        win_probability=0.62,
        confidence=0.75,
        num_observations=15,
        expected_value=0.015,
    )


@pytest.fixture
def bankroll(test_settings) -> BankrollManager:
    """BankrollManager with test settings."""
    return BankrollManager(test_settings)


@pytest.fixture
def sample_position() -> Position:
    """Sample open long position."""
    return Position(
        symbol="BTC/USDT",
        exchange="mock",
        side=PositionSide.LONG,
        quantity=0.1,
        entry_price=65000.0,
        current_price=65100.0,
        entry_order_id="test-order-1",
        strategy="mispricing",
    )
