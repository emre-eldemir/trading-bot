"""
app/risk/regime_detector.py — Market volatility regime detection.

Classifies the market into LOW / NORMAL / HIGH volatility regimes
and adjusts the risk budget accordingly.

Why regime detection?
- In high-volatility regimes, edge estimates are less reliable
- Slippage and spreads are wider
- Risk should be reduced proactively, not reactively
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.risk import VolatilityRegime
from app.utils.logging_config import Events, log_event

logger = logging.getLogger(__name__)


class RegimeDetector:
    """
    Detects current market regime from rolling volatility.

    Regimes:
    - LOW: vol < low_threshold → risk multiplier = 1.0 (normal)
    - NORMAL: low_threshold <= vol <= high_threshold → risk multiplier = 1.0
    - HIGH: vol > high_threshold → risk multiplier reduced (e.g., 0.5)
    """

    def __init__(
        self,
        window_size: int = 50,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._window_size = window_size
        self._price_history: deque[float] = deque(maxlen=window_size)
        self._current_regime: VolatilityRegime = VolatilityRegime.NORMAL
        self._current_multiplier: float = 1.0

    def update(self, price: float) -> VolatilityRegime:
        """
        Update regime with a new price observation.

        Returns current regime classification.
        """
        if price <= 0:
            return self._current_regime

        self._price_history.append(price)

        if len(self._price_history) < 10:
            return self._current_regime

        volatility = self._compute_volatility()
        new_regime = self._classify_regime(volatility)

        if new_regime != self._current_regime:
            log_event(
                logger,
                Events.REGIME_CHANGE,
                level="INFO",
                old_regime=self._current_regime.value,
                new_regime=new_regime.value,
                volatility=f"{volatility:.4f}",
            )
            self._current_regime = new_regime
            self._current_multiplier = self._get_multiplier(new_regime)

        return self._current_regime

    def _compute_volatility(self) -> float:
        """
        Rolling volatility from log returns.
        Annualised assuming ~5-second intervals.
        """
        prices = list(self._price_history)
        if len(prices) < 2:
            return 0.0

        log_returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        if not log_returns:
            return 0.0

        mean_r = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_r) ** 2 for r in log_returns) / len(log_returns)
        std = math.sqrt(variance)

        # Annualise
        intervals_per_year = 365 * 24 * 720  # ~5-second intervals
        return std * math.sqrt(intervals_per_year)

    def _classify_regime(self, volatility: float) -> VolatilityRegime:
        """Classify volatility into LOW / NORMAL / HIGH regime."""
        if volatility > self._settings.high_volatility_threshold:
            return VolatilityRegime.HIGH
        if volatility < self._settings.low_volatility_threshold:
            return VolatilityRegime.LOW
        return VolatilityRegime.NORMAL

    def _get_multiplier(self, regime: VolatilityRegime) -> float:
        """Return risk budget multiplier for the given regime."""
        if regime == VolatilityRegime.HIGH:
            return self._settings.high_vol_risk_multiplier
        return self._settings.low_vol_risk_multiplier  # LOW and NORMAL = 1.0

    @property
    def current_regime(self) -> VolatilityRegime:
        return self._current_regime

    @property
    def risk_multiplier(self) -> float:
        """Risk budget multiplier based on current regime. Apply to position sizes."""
        return self._current_multiplier

    def get_status(self) -> dict:
        return {
            "regime": self._current_regime.value,
            "risk_multiplier": self._current_multiplier,
            "price_history_len": len(self._price_history),
        }
