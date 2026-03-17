"""
app/strategies/mispricing_strategy.py — Detects price mispricings.

Logic:
- Computes a fair value estimate from recent trade history and order book
- Signals when the current best bid/ask deviates from fair value by more
  than the configured min_edge threshold (after fees and slippage)
- Uses order book depth to estimate win probability based on available liquidity
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics
from app.models.signal import Signal, SignalDirection, SignalType
from app.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class MispricingStrategy(BaseStrategy):
    """
    Detects price mispricings relative to estimated fair value.

    Fair value estimation:
    - Volume-weighted average of order book mid prices (VWAP of top N levels)
    - Compared to current best bid/ask

    Win probability estimation:
    - Based on order book depth ratio: deeper book on the target side = higher win prob
    - Clamped to [0.50, 0.85] to avoid overconfidence
    """

    def __init__(self, settings: Optional[TradingConfig] = None) -> None:
        super().__init__(name="mispricing", settings=settings)
        self._price_vwap_window: deque[float] = deque(maxlen=20)
        self._window_size: int = 20

    def name_str(self) -> str:
        return "Mispricing Detection Strategy"

    def generate_signals(
        self,
        metrics: MarketMetrics,
        context: Optional[dict] = None,
    ) -> list[Signal]:
        """
        Detect mispricing opportunities in the current order book.

        Returns BUY signal if ask < fair_value - min_edge (underpriced ask).
        Returns SELL signal if bid > fair_value + min_edge (overpriced bid).
        """
        if not self._enabled:
            return []

        if metrics.mid_price <= 0 or metrics.best_bid <= 0 or metrics.best_ask <= 0:
            return []

        # Update rolling VWAP tracker
        self._price_vwap_window.append(metrics.mid_price)

        fair_value = self._estimate_fair_value(metrics)
        if fair_value <= 0:
            return []

        signals: list[Signal] = []
        min_edge = self._settings.min_edge
        fee_cost = 2 * self._settings.taker_fee  # Round-trip fee

        # --- BUY signal: ask is below fair value ---
        ask_edge = (fair_value - metrics.best_ask) / fair_value
        if ask_edge > (min_edge + fee_cost):
            win_prob = self._estimate_win_probability(metrics, direction="buy")
            signals.append(self._build_signal(
                metrics=metrics,
                direction=SignalDirection.BUY,
                entry_price=metrics.best_ask,
                fair_value=fair_value,
                raw_edge=ask_edge,
                win_probability=win_prob,
            ))

        # --- SELL signal: bid is above fair value ---
        bid_edge = (metrics.best_bid - fair_value) / fair_value
        if bid_edge > (min_edge + fee_cost):
            win_prob = self._estimate_win_probability(metrics, direction="sell")
            signals.append(self._build_signal(
                metrics=metrics,
                direction=SignalDirection.SELL,
                entry_price=metrics.best_bid,
                fair_value=fair_value,
                raw_edge=bid_edge,
                win_probability=win_prob,
            ))

        return signals

    def _estimate_fair_value(self, metrics: MarketMetrics) -> float:
        """
        Estimate fair value using VWAP of recent mid prices.
        Falls back to current mid price if insufficient history.
        """
        if len(self._price_vwap_window) >= 3:
            return sum(self._price_vwap_window) / len(self._price_vwap_window)
        return metrics.mid_price

    def _estimate_win_probability(
        self,
        metrics: MarketMetrics,
        direction: str,
    ) -> float:
        """
        Estimate win probability from order book depth.

        For a BUY: deeper bid stack = more buyers ready = higher chance mispricing resolves.
        For a SELL: deeper ask stack = more sellers ready = higher chance.
        Base probability is 0.55 (slight edge above 50%).
        """
        total_depth = metrics.bid_depth + metrics.ask_depth
        if total_depth <= 0:
            return 0.55

        if direction == "buy":
            # Higher bid depth relative to ask → buyers are stronger → BUY more likely to win
            ratio = metrics.bid_depth / total_depth
        else:
            ratio = metrics.ask_depth / total_depth

        # Scale to [0.50, 0.80]
        return 0.50 + ratio * 0.30

    def _build_signal(
        self,
        metrics: MarketMetrics,
        direction: SignalDirection,
        entry_price: float,
        fair_value: float,
        raw_edge: float,
        win_probability: float,
    ) -> Signal:
        """Construct a Signal object from computed parameters."""
        return Signal(
            strategy=self.name,
            signal_type=SignalType.MISPRICING,
            symbol=metrics.symbol,
            exchange=metrics.exchange,
            direction=direction,
            entry_price=entry_price,
            fair_value=fair_value,
            raw_edge=raw_edge,
            win_probability=win_probability,
            confidence=min(0.90, win_probability + 0.10),
            num_observations=len(self._price_vwap_window),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._settings.signal_decay_half_life * 2),
        )
