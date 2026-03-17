"""
app/strategies/orderbook_imbalance_strategy.py — Order book imbalance detection.

Logic:
- Significant bid/ask imbalance suggests imminent price pressure
- Strong buy imbalance → price likely to rise → BUY signal
- Strong sell imbalance → price likely to fall → SELL signal
- Win probability derived from imbalance magnitude
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics
from app.models.signal import Signal, SignalDirection, SignalType
from app.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

# Threshold for triggering a signal: |imbalance| > this value
IMBALANCE_THRESHOLD = 0.30  # 30% imbalance


class OrderBookImbalanceStrategy(BaseStrategy):
    """
    Detects strong order book imbalances that suggest imminent price moves.

    Imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
    Range: [-1, +1] where +1 = all bids, -1 = all asks

    Signals are generated when |imbalance| exceeds the threshold.
    Position sizing is done by the EV engine, not here.
    """

    def __init__(
        self,
        imbalance_threshold: float = IMBALANCE_THRESHOLD,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        super().__init__(name="orderbook_imbalance", settings=settings)
        self._threshold = imbalance_threshold
        # Track imbalance history for smoothing
        self._imbalance_history: dict[str, list[float]] = {}

    def name_str(self) -> str:
        return "Order Book Imbalance Strategy"

    def generate_signals(
        self,
        metrics: MarketMetrics,
        context: Optional[dict] = None,
    ) -> list[Signal]:
        """
        Generate signals based on order book imbalance.
        Smooths imbalance over a short window to reduce false signals.
        """
        if not self._enabled:
            return []

        if metrics.mid_price <= 0:
            return []

        # Track smoothed imbalance
        sym = metrics.symbol
        if sym not in self._imbalance_history:
            self._imbalance_history[sym] = []
        self._imbalance_history[sym].append(metrics.order_book_imbalance)
        if len(self._imbalance_history[sym]) > 5:
            self._imbalance_history[sym].pop(0)

        smoothed_imbalance = sum(self._imbalance_history[sym]) / len(self._imbalance_history[sym])

        signals: list[Signal] = []

        if smoothed_imbalance > self._threshold:
            # Strong buy pressure — BUY signal
            win_prob = self._imbalance_to_win_prob(smoothed_imbalance, bullish=True)
            edge = smoothed_imbalance * metrics.spread_pct  # Proxy edge: imbalance × spread
            if edge > self._settings.min_edge:
                signals.append(self._build_signal(
                    metrics=metrics,
                    direction=SignalDirection.BUY,
                    imbalance=smoothed_imbalance,
                    win_probability=win_prob,
                    edge=edge,
                ))

        elif smoothed_imbalance < -self._threshold:
            # Strong sell pressure — SELL signal
            win_prob = self._imbalance_to_win_prob(abs(smoothed_imbalance), bullish=False)
            edge = abs(smoothed_imbalance) * metrics.spread_pct
            if edge > self._settings.min_edge:
                signals.append(self._build_signal(
                    metrics=metrics,
                    direction=SignalDirection.SELL,
                    imbalance=smoothed_imbalance,
                    win_probability=win_prob,
                    edge=edge,
                ))

        return signals

    def _imbalance_to_win_prob(self, imbalance: float, bullish: bool) -> float:
        """
        Convert imbalance magnitude to a win probability.
        |imbalance| = 0.3 → prob ≈ 0.55
        |imbalance| = 0.7 → prob ≈ 0.68
        Capped at 0.75 to avoid overconfidence.
        """
        # Linear scaling: 0.50 + 0.25 * imbalance (capped at 0.75)
        return min(0.75, 0.50 + 0.25 * abs(imbalance))

    def _build_signal(
        self,
        metrics: MarketMetrics,
        direction: SignalDirection,
        imbalance: float,
        win_probability: float,
        edge: float,
    ) -> Signal:
        entry = metrics.best_ask if direction == SignalDirection.BUY else metrics.best_bid
        return Signal(
            strategy=self.name,
            signal_type=SignalType.ORDERBOOK_IMBALANCE,
            symbol=metrics.symbol,
            exchange=metrics.exchange,
            direction=direction,
            entry_price=entry,
            fair_value=metrics.mid_price,
            raw_edge=edge,
            win_probability=win_probability,
            confidence=win_probability * 0.85,  # Slightly discounted
            num_observations=len(self._imbalance_history.get(metrics.symbol, [1])),
            expires_at=datetime.utcnow() + timedelta(seconds=30),  # Imbalance signals expire fast
            notes=f"imbalance={imbalance:.3f}",
        )
