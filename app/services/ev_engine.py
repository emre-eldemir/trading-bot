"""
app/services/ev_engine.py — Expected Value calculation engine.

Takes signals from strategies and computes net EV after:
  - Maker/taker fees (separate, prefer maker when possible)
  - Dynamic L2 slippage
  - Execution delay cost
  - Signal decay (stale signal EV reduction)
  - Bayesian edge confidence adjustment

Only signals with EV > min_ev are returned as actionable.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics
from app.models.signal import Signal
from app.utils.math_helpers import (
    bayesian_edge_confidence,
    ev_after_fees,
    ev_after_slippage,
    expected_value,
    signal_decay_factor,
)

logger = logging.getLogger(__name__)


class EVEngine:
    """
    Evaluates trading signals and computes adjusted Expected Value.

    Decision flow:
    1. Check if signal is expired or stale
    2. Apply signal decay to raw edge
    3. Apply Bayesian confidence adjustment
    4. Compute EV with dynamic slippage from L2 data
    5. Deduct fees (maker or taker depending on order type)
    6. Deduct execution delay cost estimate
    7. Filter by min_edge and min_ev thresholds
    """

    def __init__(self, settings: Optional[TradingConfig] = None) -> None:
        self._settings = settings or get_settings()

    def evaluate(
        self,
        signal: Signal,
        metrics: MarketMetrics,
        position_size: float = 1.0,
        use_maker: bool = True,
    ) -> Optional[Signal]:
        """
        Evaluate a signal and return it with updated EV fields, or None if rejected.

        Args:
            signal: Raw signal from a strategy.
            metrics: Current market metrics for the symbol.
            position_size: Intended position size (in base currency units).
            use_maker: Whether to use maker (limit) fees or taker (market) fees.

        Returns:
            Updated Signal with net_ev fields, or None if below thresholds.
        """
        # 1. Reject expired signals
        if signal.is_expired:
            logger.debug("Signal %s expired — rejected", signal.id)
            return None

        # 2. Reject signals without minimum confidence
        if signal.confidence < self._settings.min_confidence:
            logger.debug(
                "Signal %s confidence %.2f below minimum %.2f — rejected",
                signal.id, signal.confidence, self._settings.min_confidence,
            )
            return None

        # 3. Apply signal decay — EV degrades as signal ages
        decay = signal_decay_factor(signal.age_seconds, self._settings.signal_decay_half_life)
        decayed_edge = signal.raw_edge * decay

        # 4. Bayesian confidence adjustment
        posterior_edge, bayes_confidence = bayesian_edge_confidence(
            observed_edge=decayed_edge,
            num_observations=signal.num_observations,
        )
        # Update signal confidence with Bayesian weight
        adjusted_confidence = min(signal.confidence, bayes_confidence)
        adjusted_edge = posterior_edge * adjusted_confidence

        # 5. Check minimum edge threshold
        if abs(adjusted_edge) < self._settings.min_edge:
            logger.debug(
                "Signal %s edge %.4f below min_edge %.4f — rejected",
                signal.id, adjusted_edge, self._settings.min_edge,
            )
            return None

        # 6. Compute raw EV based on win probability and adjusted edge
        # win_amount = edge * position_size, loss_amount = position_size * loss_fraction
        # For a mispricing trade: win = edge, loss = spread + slippage
        win_prob = signal.win_probability
        win_amount = abs(adjusted_edge) * position_size
        loss_amount = (metrics.spread_pct + metrics.estimated_slippage_buy) * position_size
        raw_ev = expected_value(win_prob, win_amount, loss_amount)

        # 7. Deduct fees (both entry and exit — round trip)
        fee_rate = self._settings.maker_fee if use_maker else self._settings.taker_fee
        fee_cost = 2.0 * position_size * fee_rate
        ev_net_fees = raw_ev - fee_cost

        # 8. Deduct L2 slippage cost
        slippage = (
            metrics.estimated_slippage_buy
            if signal.direction.value == "buy"
            else metrics.estimated_slippage_sell
        )
        ev_net_slippage = ev_net_fees - slippage * position_size

        # 9. Execution delay cost: opportunity may move against us in delay window
        # Approximation: delay_cost = volatility * sqrt(delay) * position_size * 0.5
        import math
        delay_cost = (
            metrics.volatility
            * math.sqrt(self._settings.execution_delay / (365 * 24 * 3600))
            * position_size
            * 0.5
        )
        net_ev = ev_net_slippage - delay_cost

        # 10. Apply minimum EV threshold
        if net_ev < self._settings.min_ev * position_size:
            logger.debug(
                "Signal %s net_ev %.6f below min_ev threshold — rejected",
                signal.id, net_ev,
            )
            return None

        # Return updated signal with computed EV
        updated = signal.model_copy(update={
            "raw_edge": decayed_edge,
            "expected_value": net_ev,
            "confidence": adjusted_confidence,
        })

        logger.debug(
            "Signal %s accepted: raw_edge=%.4f, net_ev=%.6f, confidence=%.2f",
            signal.id, decayed_edge, net_ev, adjusted_confidence,
        )
        return updated

    def batch_evaluate(
        self,
        signals: list[Signal],
        metrics_map: dict[str, MarketMetrics],
        position_size: float = 1.0,
    ) -> list[Signal]:
        """
        Evaluate a batch of signals and return only those with positive EV.
        Results are sorted by EV descending (best opportunities first).
        """
        accepted: list[Signal] = []
        for signal in signals:
            metrics = metrics_map.get(signal.symbol)
            if metrics is None:
                logger.warning("No metrics for symbol %s — skipping signal", signal.symbol)
                continue
            result = self.evaluate(signal, metrics, position_size)
            if result is not None:
                accepted.append(result)

        # Sort by expected_value descending
        accepted.sort(key=lambda s: s.expected_value, reverse=True)
        return accepted
