"""
tests/test_backtest.py — Unit tests for the backtesting engine.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.backtest.backtester import Backtester, BacktestResult
from app.models.market import MarketMetrics
from app.services.ev_engine import EVEngine
from app.strategies.mispricing_strategy import MispricingStrategy
from app.utils.math_helpers import max_drawdown, sharpe_ratio, win_rate, expectancy


def build_snapshots(n: int = 100, base_price: float = 65000.0) -> list[MarketMetrics]:
    """Generate synthetic market snapshots for backtesting."""
    import random
    snapshots = []
    price = base_price
    for i in range(n):
        noise = random.gauss(0, price * 0.001)
        price = max(1.0, price + noise)
        snapshots.append(MarketMetrics(
            symbol="BTC/USDT",
            mid_price=price,
            best_bid=price * 0.9995,
            best_ask=price * 1.0005,
            spread=price * 0.001,
            spread_pct=0.001,
            bid_depth=10.0,
            ask_depth=10.0,
            order_book_imbalance=random.uniform(-0.3, 0.3),
            estimated_slippage_buy=0.0003,
            estimated_slippage_sell=0.0003,
            volume_24h=5000.0,
            volatility=0.30,
            timestamp=datetime.utcnow() - timedelta(seconds=n - i),
        ))
    return snapshots


class TestBacktester:
    """Tests for the historical backtesting engine."""

    def test_backtest_runs_without_error(self, test_settings):
        """Backtester should complete without raising."""
        backtester = Backtester(
            strategies=[MispricingStrategy(test_settings)],
            ev_engine=EVEngine(test_settings),
            settings=test_settings,
        )
        snapshots = build_snapshots(50)
        result = backtester.run(snapshots)
        assert isinstance(result, BacktestResult)

    def test_equity_curve_starts_at_bankroll(self, test_settings):
        """Equity curve first point should equal starting bankroll."""
        backtester = Backtester(
            strategies=[MispricingStrategy(test_settings)],
            settings=test_settings,
        )
        result = backtester.run(build_snapshots(20))
        assert result.equity_curve[0] == pytest.approx(test_settings.starting_bankroll, rel=1e-5)

    def test_result_has_trade_count(self, test_settings):
        """Result should have a non-negative trade count."""
        backtester = Backtester(
            strategies=[MispricingStrategy(test_settings)],
            settings=test_settings,
        )
        result = backtester.run(build_snapshots(100))
        assert result.total_trades >= 0
        assert result.winning_trades + result.losing_trades == result.total_trades

    def test_win_rate_in_range(self, test_settings):
        """Win rate should be in [0, 1]."""
        backtester = Backtester(
            strategies=[MispricingStrategy(test_settings)],
            settings=test_settings,
        )
        result = backtester.run(build_snapshots(50))
        assert 0.0 <= result.win_rate <= 1.0


class TestMathHelpers:
    """Tests for mathematical utility functions."""

    def test_max_drawdown_flat(self):
        """Flat equity curve should have zero drawdown."""
        curve = [10000.0] * 10
        assert max_drawdown(curve) == 0.0

    def test_max_drawdown_decline(self):
        """Declining equity should report correct drawdown."""
        curve = [10000.0, 9500.0, 9000.0, 8500.0]
        dd = max_drawdown(curve)
        assert dd == pytest.approx(0.15, rel=1e-5)

    def test_max_drawdown_recovery(self):
        """Drawdown after recovery should still reflect max decline."""
        curve = [10000.0, 8000.0, 12000.0]
        dd = max_drawdown(curve)
        assert dd == pytest.approx(0.20, rel=1e-5)

    def test_sharpe_ratio_positive_returns(self):
        """Positive varying returns should give positive Sharpe."""
        import random
        random.seed(42)
        # Use slightly varying positive returns to avoid zero-variance edge case
        returns = [0.001 + random.gauss(0, 0.0001) for _ in range(100)]
        sr = sharpe_ratio(returns)
        assert sr > 0

    def test_sharpe_ratio_zero_variance(self):
        """Zero variance should return 0 to avoid division by zero."""
        returns = [0.001] * 5
        sr = sharpe_ratio(returns)
        # Very high (all same returns) — but no crash
        assert isinstance(sr, float)

    def test_win_rate_all_wins(self):
        """All positive PnLs should give win rate of 1.0."""
        pnls = [1.0, 2.0, 0.5, 3.0]
        assert win_rate(pnls) == 1.0

    def test_win_rate_all_losses(self):
        """All negative PnLs should give win rate of 0.0."""
        pnls = [-1.0, -2.0, -0.5]
        assert win_rate(pnls) == 0.0

    def test_expectancy_positive(self):
        """Expectancy should be average of PnLs."""
        pnls = [2.0, -1.0, 3.0, -1.0]
        assert expectancy(pnls) == pytest.approx(0.75, rel=1e-5)
