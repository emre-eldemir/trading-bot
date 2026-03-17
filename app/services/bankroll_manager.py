"""
app/services/bankroll_manager.py — Bankroll and capital management.

Implements a tiered bankroll: only active_capital_ratio of total equity
is available for trading. The rest is "cold reserve" and cannot be touched.

Also tracks daily PnL, drawdown, and provides capital availability checks.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from app.config import TradingConfig, get_settings

logger = logging.getLogger(__name__)


class BankrollManager:
    """
    Manages the trading bankroll.

    Tier structure:
    - total_equity: Full account equity
    - active_capital: total_equity * active_capital_ratio (available to trade)
    - cold_reserve: total_equity * (1 - active_capital_ratio) (untouchable)

    The active capital shrinks as positions are opened and grows as they close.
    """

    def __init__(self, settings: Optional[TradingConfig] = None) -> None:
        self._settings = settings or get_settings()
        self._total_equity: float = self._settings.starting_bankroll
        self._peak_equity: float = self._settings.starting_bankroll
        self._committed_capital: float = 0.0  # Capital in open positions
        self._daily_start_equity: float = self._settings.starting_bankroll
        self._daily_reset_date: date = datetime.utcnow().date()
        self._pnl_history: list[float] = []

    # ------------------------------------------------------------------ #
    #  Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def total_equity(self) -> float:
        return self._total_equity

    @property
    def active_capital(self) -> float:
        """Capital available for new trades (tiered bankroll)."""
        return self._total_equity * self._settings.active_capital_ratio

    @property
    def cold_reserve(self) -> float:
        """Capital permanently held back — NOT used for trading."""
        return self._total_equity * (1.0 - self._settings.active_capital_ratio)

    @property
    def available_capital(self) -> float:
        """Active capital minus what's already committed to open positions."""
        return max(0.0, self.active_capital - self._committed_capital)

    @property
    def current_drawdown(self) -> float:
        """Current drawdown from peak equity."""
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - self._total_equity) / self._peak_equity)

    @property
    def daily_pnl(self) -> float:
        """PnL since daily session started (resets at UTC midnight)."""
        self._maybe_reset_daily()
        return self._total_equity - self._daily_start_equity

    @property
    def daily_pnl_pct(self) -> float:
        if self._daily_start_equity <= 0:
            return 0.0
        return self.daily_pnl / self._daily_start_equity

    # ------------------------------------------------------------------ #
    #  Capital operations                                                  #
    # ------------------------------------------------------------------ #

    def allocate(self, amount: float) -> bool:
        """
        Reserve capital for a new trade.

        Returns True if allocation succeeded, False if insufficient capital.
        """
        if amount <= 0:
            return False
        if amount > self.available_capital:
            logger.warning(
                "Allocation request %.2f exceeds available capital %.2f",
                amount, self.available_capital,
            )
            return False
        self._committed_capital += amount
        logger.debug("Allocated %.2f | committed=%.2f", amount, self._committed_capital)
        return True

    def release(self, amount: float, pnl: float = 0.0) -> None:
        """
        Release capital when a position is closed.

        Also updates total equity with realised PnL.
        """
        self._committed_capital = max(0.0, self._committed_capital - amount)
        self._total_equity += pnl
        self._peak_equity = max(self._peak_equity, self._total_equity)
        self._pnl_history.append(pnl)
        logger.debug(
            "Released %.2f | pnl=%.4f | equity=%.2f | drawdown=%.2f%%",
            amount, pnl, self._total_equity, self.current_drawdown * 100,
        )

    def has_sufficient_capital(self, required: float) -> bool:
        """Check if enough capital is available without allocating it."""
        return self.available_capital >= required and \
               self.available_capital >= self._settings.min_active_capital

    # ------------------------------------------------------------------ #
    #  Drawdown / daily reset                                              #
    # ------------------------------------------------------------------ #

    def _maybe_reset_daily(self) -> None:
        """Reset daily PnL tracking at UTC midnight."""
        today = datetime.utcnow().date()
        if today != self._daily_reset_date:
            self._daily_start_equity = self._total_equity
            self._daily_reset_date = today
            logger.info("Daily PnL reset | new_start=%.2f", self._daily_start_equity)

    def get_summary(self) -> dict:
        """Return a snapshot of current bankroll state."""
        return {
            "total_equity": self._total_equity,
            "active_capital": self.active_capital,
            "cold_reserve": self.cold_reserve,
            "committed_capital": self._committed_capital,
            "available_capital": self.available_capital,
            "peak_equity": self._peak_equity,
            "current_drawdown": self.current_drawdown,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": self.daily_pnl_pct,
        }
