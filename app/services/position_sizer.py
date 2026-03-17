"""
app/services/position_sizer.py — Kelly-based position sizing.

Implements:
- Fractional Kelly Criterion
- Dynamic Kelly fraction (reduces with drawdown)
- Correlation-adjusted Kelly (reduces with correlated open positions)
- Position size clamping to min/max limits

All formulas documented in MATH_DOCS.md.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.signal import Signal
from app.services.bankroll_manager import BankrollManager
from app.utils.math_helpers import (
    correlation_adjusted_kelly,
    dynamic_kelly_fraction,
    fractional_kelly,
)

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    Computes optimal position sizes using Fractional Kelly Criterion.

    Why Fractional Kelly?
    - Full Kelly maximises long-run growth but has very high variance
    - Edge estimates are often overconfident in practice
    - 0.25 Kelly (quarter Kelly) is used here as a conservative default
    - Drawdown-adaptive: automatically reduces fraction as losses mount
    """

    def __init__(
        self,
        bankroll_manager: BankrollManager,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._bankroll = bankroll_manager
        self._settings = settings or get_settings()

    def compute_size(
        self,
        signal: Signal,
        open_positions_sizes: Optional[list[float]] = None,
        open_positions_correlations: Optional[list[float]] = None,
    ) -> float:
        """
        Compute the recommended position size in bankroll fraction.

        Steps:
        1. Compute base fractional Kelly
        2. Apply dynamic fraction (drawdown-adjusted)
        3. Apply correlation adjustment
        4. Clamp to min/max limits
        5. Check available capital

        Args:
            signal: The evaluated signal (must have win_probability and raw_edge).
            open_positions_sizes: Sizes of currently open positions (bankroll fractions).
            open_positions_correlations: Correlations of open positions with new trade.

        Returns:
            Position size as a fraction of total equity (e.g., 0.05 = 5%).
        """
        # 1. Compute base fractional Kelly
        # For a mispricing trade:
        #   win_payout = raw_edge (fraction of position gained on win)
        #   loss_payout = spread + fees (fraction of position lost on loss)
        # b = win_payout / loss_payout (payout ratio)
        # Using a small but realistic loss fraction (spread/fee equivalent)
        win_payout = max(signal.raw_edge, 0.001)
        loss_payout = max(
            self._settings.slippage_buffer + self._settings.taker_fee * 2,
            0.001,
        )
        base_size = fractional_kelly(
            win_probability=signal.win_probability,
            win_payout=win_payout,
            fraction=self._settings.kelly_fraction,
            loss_payout=loss_payout,
        )

        if base_size <= 0:
            logger.debug("Signal %s: Kelly returns no-bet (edge negative)", signal.id)
            return 0.0

        # 2. Dynamic Kelly fraction: reduce as drawdown increases
        current_drawdown = self._bankroll.current_drawdown
        dynamic_fraction = dynamic_kelly_fraction(
            base_fraction=self._settings.kelly_fraction,
            current_drawdown=current_drawdown,
            thresholds=self._settings.drawdown_reduction_thresholds,
        )
        # Recalculate with dynamic fraction
        dynamic_size = fractional_kelly(
            win_probability=signal.win_probability,
            win_payout=win_payout,
            fraction=dynamic_fraction,
            loss_payout=loss_payout,
        )

        # 3. Correlation-adjusted Kelly
        corr_adjusted = correlation_adjusted_kelly(
            kelly_size=dynamic_size,
            open_positions=open_positions_sizes or [],
            correlations=open_positions_correlations or [],
            correlation_threshold=self._settings.correlation_threshold,
        )

        # 4. Apply risk multiplier from risk manager (regime-based)
        # (The caller can override by adjusting the fraction before calling)

        # 5. Clamp to configured min/max position limits
        if corr_adjusted <= 0:
            return 0.0
        final_size = max(
            self._settings.min_position_fraction,
            min(self._settings.max_position_fraction, corr_adjusted),
        )

        # 6. Also cap by single trade risk limit
        final_size = min(final_size, self._settings.max_single_trade_risk)

        logger.debug(
            "Position sizing | signal=%s | base=%.4f | dynamic=%.4f | "
            "corr_adj=%.4f | final=%.4f | drawdown=%.2f%%",
            signal.id, base_size, dynamic_size, corr_adjusted,
            final_size, current_drawdown * 100,
        )
        return final_size

    def compute_dollar_size(
        self,
        signal: Signal,
        open_positions_sizes: Optional[list[float]] = None,
        open_positions_correlations: Optional[list[float]] = None,
    ) -> float:
        """
        Compute position size in dollar (equity) terms.

        Returns 0.0 if insufficient capital available.
        """
        fraction = self.compute_size(signal, open_positions_sizes, open_positions_correlations)
        dollar_size = fraction * self._bankroll.total_equity

        if dollar_size <= 0:
            return 0.0

        if not self._bankroll.has_sufficient_capital(dollar_size):
            logger.warning(
                "Insufficient capital: required=%.2f available=%.2f",
                dollar_size, self._bankroll.available_capital,
            )
            # Reduce to available capital
            dollar_size = self._bankroll.available_capital * 0.95  # Safety buffer

        return max(0.0, dollar_size)
