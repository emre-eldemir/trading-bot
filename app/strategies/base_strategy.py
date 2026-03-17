"""
app/strategies/base_strategy.py — Abstract base class for all strategies.

All strategies implement this interface, enabling plug-in architecture.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics
from app.models.signal import Signal

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    Abstract base for all trading strategies.

    Strategies do NOT predict price direction.
    They detect mispricings, imbalances, and EV opportunities.
    """

    def __init__(
        self,
        name: str,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self.name = name
        self._settings = settings or get_settings()
        self._enabled: bool = True

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True
        logger.info("Strategy %s enabled", self.name)

    def disable(self) -> None:
        self._enabled = False
        logger.info("Strategy %s disabled", self.name)

    @abstractmethod
    def generate_signals(
        self,
        metrics: MarketMetrics,
        context: Optional[dict] = None,
    ) -> list[Signal]:
        """
        Analyse market metrics and return a list of signals.

        Args:
            metrics: Latest market metrics for the symbol.
            context: Optional additional context (e.g., cross-market data).

        Returns:
            List of raw signals (not yet EV-filtered).
        """
        ...

    @abstractmethod
    def name_str(self) -> str:
        """Human-readable strategy name."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, enabled={self._enabled})"
