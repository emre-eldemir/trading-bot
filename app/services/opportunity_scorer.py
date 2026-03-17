"""
app/services/opportunity_scorer.py — Opportunity scoring and filtering.

Scores trading opportunities using a multi-factor rule-based system.
ML layer is optional and can be added without breaking the interface.

Factors:
- EV magnitude (40%)
- Liquidity / depth (25%)
- Bayesian confidence (20%)
- Signal freshness (15%)
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics
from app.models.signal import Signal
from app.utils.math_helpers import signal_decay_factor

logger = logging.getLogger(__name__)


class OpportunityScorer:
    """
    Scores and ranks trading opportunities.

    Design: Rule-based scoring by default. The _ml_score() method is a
    stub that can be populated with a real ML model later — the interface
    (return float in [0,1]) remains the same.
    """

    def __init__(self, settings: Optional[TradingConfig] = None) -> None:
        self._settings = settings or get_settings()
        self._ml_model = None  # Populated if ML is enabled

    def score(self, signal: Signal, metrics: MarketMetrics) -> float:
        """
        Compute a composite score in [0, 1] for an opportunity.

        Higher score = more attractive opportunity.
        Returns 0.0 for clearly invalid inputs.
        """
        ev_score = self._score_ev(signal.expected_value, metrics.mid_price)
        liquidity_score = self._score_liquidity(metrics)
        confidence_score = self._score_confidence(signal.confidence)
        freshness_score = self._score_freshness(signal.age_seconds)

        # Weighted combination
        composite = (
            self._settings.ev_weight * ev_score
            + self._settings.liquidity_weight * liquidity_score
            + self._settings.confidence_weight * confidence_score
            + self._settings.freshness_weight * freshness_score
        )

        # Optional: multiply by ML model output if available
        if self._ml_model is not None:
            ml_factor = self._ml_score(signal, metrics)
            composite *= ml_factor

        score = max(0.0, min(1.0, composite))
        logger.debug(
            "Score | signal=%s | ev=%.2f | liq=%.2f | conf=%.2f | fresh=%.2f | composite=%.2f",
            signal.id[:8], ev_score, liquidity_score, confidence_score, freshness_score, score,
        )
        return score

    def _score_ev(self, ev: float, mid_price: float) -> float:
        """
        Score based on EV magnitude.
        Normalise EV relative to mid price — small absolute EV on a $100 asset
        is very different from $100 EV on a $100,000 asset.
        """
        if mid_price <= 0:
            return 0.0
        relative_ev = ev / (mid_price + 1e-9)
        # Sigmoid-like scaling: 0.05 relative EV → ~1.0 score
        import math
        return min(1.0, 2.0 * math.tanh(relative_ev / 0.01))

    def _score_liquidity(self, metrics: MarketMetrics) -> float:
        """
        Score based on order book liquidity.
        Good liquidity: tight spread, deep book, balanced imbalance.
        """
        # Tight spread is better (max spread ~1% gets score 0)
        spread_score = max(0.0, 1.0 - metrics.spread_pct / 0.01)

        # Deeper book is better (normalise at 1000 units)
        total_depth = metrics.bid_depth + metrics.ask_depth
        depth_score = min(1.0, total_depth / 1000.0)

        return 0.5 * spread_score + 0.5 * depth_score

    def _score_confidence(self, confidence: float) -> float:
        """Score proportional to Bayesian confidence [0, 1]."""
        return max(0.0, min(1.0, confidence))

    def _score_freshness(self, age_seconds: float) -> float:
        """Score based on signal age — fresher signals score higher."""
        return signal_decay_factor(age_seconds, self._settings.signal_decay_half_life)

    def _ml_score(self, signal: Signal, metrics: MarketMetrics) -> float:
        """
        Optional ML model scoring stub.

        Replace with actual model prediction when ready.
        Must return a float in [0, 1].
        """
        # Stub: return 1.0 (no modification)
        return 1.0

    def filter_and_rank(
        self,
        signals: list[Signal],
        metrics_map: dict[str, MarketMetrics],
    ) -> list[tuple[Signal, float]]:
        """
        Score all signals and return those above min_score, sorted by score.

        Returns:
            List of (signal, score) tuples sorted by score descending.
        """
        scored: list[tuple[Signal, float]] = []
        for signal in signals:
            metrics = metrics_map.get(signal.symbol)
            if metrics is None:
                continue
            score = self.score(signal, metrics)
            if score >= self._settings.min_score:
                scored.append((signal, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored
