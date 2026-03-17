"""
app/backtest/backtester.py — Historical data backtesting engine.

Replays historical market snapshots through the strategy pipeline
to evaluate performance without real money.

Features:
- Replays historical order book and trade data
- Applies realistic fees, slippage, and execution delay
- Tracks full PnL, win rate, drawdown, Sharpe
- Outputs results to reporter
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics, OrderBook
from app.models.signal import Signal
from app.models.trade import Trade
from app.services.ev_engine import EVEngine
from app.services.bankroll_manager import BankrollManager
from app.services.position_sizer import PositionSizer
from app.strategies.base_strategy import BaseStrategy
from app.utils.math_helpers import max_drawdown, sharpe_ratio, win_rate, expectancy

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Container for backtest performance metrics."""
    start_equity: float = 10000.0
    end_equity: float = 10000.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    expectancy: float = 0.0
    avg_trade_duration: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def return_pct(self) -> float:
        if self.start_equity <= 0:
            return 0.0
        return (self.end_equity - self.start_equity) / self.start_equity


class Backtester:
    """
    Backtest engine for historical strategy evaluation.

    Usage:
        backtester = Backtester(strategies=[...], settings=settings)
        result = backtester.run(historical_data)
    """

    def __init__(
        self,
        strategies: list[BaseStrategy],
        ev_engine: Optional[EVEngine] = None,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._strategies = strategies
        self._settings = settings or get_settings()
        self._ev_engine = ev_engine or EVEngine(settings)
        self._bankroll = BankrollManager(settings)
        self._sizer = PositionSizer(self._bankroll, settings)

    def run(
        self,
        market_snapshots: list[MarketMetrics],
        symbol: str = "BTC/USDT",
    ) -> BacktestResult:
        """
        Run backtest over a sequence of market snapshots.

        Args:
            market_snapshots: Ordered list of MarketMetrics (oldest first).
            symbol: Symbol to backtest.

        Returns:
            BacktestResult with full performance metrics.
        """
        result = BacktestResult(
            start_equity=self._settings.starting_bankroll,
            end_equity=self._settings.starting_bankroll,
            start_time=market_snapshots[0].timestamp if market_snapshots else None,
        )

        trades: list[Trade] = []
        equity_curve: list[float] = [self._settings.starting_bankroll]
        open_position: Optional[dict] = None  # Simplified: single open position for backtest

        metrics_map = {symbol: market_snapshots[0]} if market_snapshots else {}

        for snapshot in market_snapshots:
            metrics_map[symbol] = snapshot

            # Check if open position should be closed (simple: close after 1 period)
            if open_position:
                # Simplified exit: close position if EV has decayed below threshold
                signal_age = (snapshot.timestamp - open_position["opened_at"]).total_seconds()
                decay = 2.0 ** (-signal_age / self._settings.signal_decay_half_life)

                if decay < 0.3 or signal_age > 120:  # Close if too stale
                    exit_price = snapshot.mid_price
                    trade = self._close_simulated_position(open_position, exit_price)
                    trades.append(trade)
                    self._bankroll.release(
                        open_position["dollar_size"],
                        pnl=trade.net_pnl,
                    )
                    equity_curve.append(self._bankroll.total_equity)
                    open_position = None

            if open_position:
                continue  # Only one position at a time in simplified backtest

            # Generate signals from strategies
            all_signals: list[Signal] = []
            for strategy in self._strategies:
                try:
                    sigs = strategy.generate_signals(snapshot)
                    all_signals.extend(sigs)
                except Exception as e:
                    logger.debug("Strategy error: %s", e)

            # Evaluate EV
            evaluated = self._ev_engine.batch_evaluate(all_signals, metrics_map)
            if not evaluated:
                continue

            best_signal = evaluated[0]
            dollar_size = self._sizer.compute_dollar_size(best_signal)

            if dollar_size <= 0:
                continue

            # Open simulated position
            open_position = {
                "signal": best_signal,
                "entry_price": best_signal.entry_price,
                "quantity": dollar_size / best_signal.entry_price if best_signal.entry_price > 0 else 0,
                "dollar_size": dollar_size,
                "opened_at": snapshot.timestamp,
            }

            if self._bankroll.allocate(dollar_size):
                logger.debug("Backtest: opened position %s @%.4f", symbol, best_signal.entry_price)

        # Close any remaining open position
        if open_position and market_snapshots:
            final_price = market_snapshots[-1].mid_price
            trade = self._close_simulated_position(open_position, final_price)
            trades.append(trade)
            self._bankroll.release(open_position["dollar_size"], pnl=trade.net_pnl)

        # Compute metrics
        pnls = [t.net_pnl for t in trades]
        equity_curve.append(self._bankroll.total_equity)

        result.end_equity = self._bankroll.total_equity
        result.end_time = market_snapshots[-1].timestamp if market_snapshots else None
        result.total_trades = len(trades)
        result.winning_trades = sum(1 for t in trades if t.net_pnl > 0)
        result.losing_trades = sum(1 for t in trades if t.net_pnl <= 0)
        result.win_rate = win_rate(pnls)
        result.total_pnl = sum(t.gross_pnl for t in trades)
        result.total_fees = sum(t.fees for t in trades)
        result.total_slippage = sum(t.slippage for t in trades)
        result.net_pnl = sum(pnls)
        result.max_drawdown = max_drawdown(equity_curve)
        result.sharpe_ratio = sharpe_ratio(pnls)
        result.expectancy = expectancy(pnls)
        result.avg_trade_duration = (
            sum(t.hold_duration_seconds for t in trades) / len(trades) if trades else 0
        )
        result.best_trade = max(pnls, default=0.0)
        result.worst_trade = min(pnls, default=0.0)
        result.equity_curve = equity_curve
        result.trades = trades

        logger.info(
            "Backtest complete: %d trades | net_pnl=%.2f | win_rate=%.1f%% | "
            "max_dd=%.1f%% | sharpe=%.2f",
            result.total_trades,
            result.net_pnl,
            result.win_rate * 100,
            result.max_drawdown * 100,
            result.sharpe_ratio,
        )
        return result

    def _close_simulated_position(self, position: dict, exit_price: float) -> Trade:
        """Build a Trade from a simulated backtest position."""
        entry_price = position["entry_price"]
        quantity = position["quantity"]
        signal = position["signal"]

        entry_value = entry_price * quantity
        exit_value = exit_price * quantity

        if signal.direction.value == "buy":
            gross_pnl = exit_value - entry_value
        else:
            gross_pnl = entry_value - exit_value

        fees = (entry_value + exit_value) * self._settings.taker_fee
        slippage = (entry_value + exit_value) * self._settings.slippage_buffer
        net_pnl = gross_pnl - fees - slippage

        return Trade(
            symbol=signal.symbol,
            exchange=signal.exchange,
            direction=signal.direction.value,
            entry_order_id="backtest",
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            gross_pnl=gross_pnl,
            fees=fees,
            slippage=slippage,
            net_pnl=net_pnl,
            strategy=signal.strategy,
            signal_id=signal.id,
            opened_at=position["opened_at"],
            closed_at=datetime.now(timezone.utc),
            hold_duration_seconds=(
                datetime.now(timezone.utc) - position["opened_at"]
            ).total_seconds(),
        )
