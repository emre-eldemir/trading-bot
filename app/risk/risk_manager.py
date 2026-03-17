"""
app/risk/risk_manager.py — Central risk management controller.

Enforces all risk rules before any trade is executed:
1. Daily max loss limit
2. Total drawdown limit (triggers kill switch)
3. Max open positions
4. Max single trade risk
5. Max correlated exposure
6. Regime-based risk reduction

The risk manager is the last gate before order submission.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.position import Position
from app.models.risk import RiskEvent, RiskEventType, RiskState, VolatilityRegime
from app.models.signal import Signal
from app.risk.kill_switch import KillSwitch
from app.risk.regime_detector import RegimeDetector
from app.services.bankroll_manager import BankrollManager
from app.utils.alerting import get_alert_manager
from app.utils.logging_config import Events, log_event

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Enforces all configured risk limits.

    All components MUST call check_pre_trade() before submitting any order.
    If this returns False, the trade must be rejected.
    """

    def __init__(
        self,
        bankroll: BankrollManager,
        kill_switch: KillSwitch,
        regime_detector: RegimeDetector,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._bankroll = bankroll
        self._kill_switch = kill_switch
        self._regime = regime_detector
        self._settings = settings or get_settings()
        self._risk_events: list[RiskEvent] = []

    # ------------------------------------------------------------------ #
    #  Pre-trade gate                                                      #
    # ------------------------------------------------------------------ #

    def check_pre_trade(
        self,
        signal: Signal,
        proposed_size: float,
        open_positions: list[Position],
    ) -> tuple[bool, str]:
        """
        Run all risk checks before a trade is submitted.

        Args:
            signal: The signal to be executed.
            proposed_size: Dollar size of the proposed trade.
            open_positions: List of currently open positions.

        Returns:
            (allowed, reason) — reason is empty string if allowed.
        """
        # 0. Kill switch check
        if self._kill_switch.is_active:
            return False, "Kill switch is active"

        # 1. Daily loss limit
        if self._bankroll.daily_pnl_pct <= -self._settings.daily_max_loss:
            reason = f"Daily loss limit hit: {self._bankroll.daily_pnl_pct:.2%}"
            self._record_event(RiskEventType.DAILY_LOSS_LIMIT, reason)
            return False, reason

        # 2. Drawdown limit
        drawdown = self._bankroll.current_drawdown
        if drawdown >= self._settings.max_drawdown:
            reason = f"Max drawdown reached: {drawdown:.2%}"
            self._record_event(RiskEventType.DRAWDOWN_LIMIT, reason, value=drawdown)
            self._kill_switch.activate(f"Max drawdown {drawdown:.2%} exceeded")
            return False, reason

        # 3. Max open positions
        if len(open_positions) >= self._settings.max_open_positions:
            reason = f"Max open positions reached: {len(open_positions)}"
            self._record_event(RiskEventType.MAX_POSITIONS, reason)
            return False, reason

        # 4. Single trade risk limit
        if proposed_size / max(self._bankroll.total_equity, 1) > self._settings.max_single_trade_risk:
            reason = (
                f"Single trade risk {proposed_size / self._bankroll.total_equity:.2%} "
                f"exceeds limit {self._settings.max_single_trade_risk:.2%}"
            )
            self._record_event(RiskEventType.SINGLE_TRADE_RISK, reason)
            return False, reason

        # 5. Correlated exposure limit
        corr_exposure = self._compute_correlated_exposure(signal.symbol, open_positions)
        if corr_exposure > self._settings.max_correlated_exposure:
            reason = f"Correlated exposure {corr_exposure:.2%} exceeds limit"
            self._record_event(RiskEventType.CORRELATED_EXPOSURE, reason, value=corr_exposure)
            return False, reason

        # 6. Available capital check
        if not self._bankroll.has_sufficient_capital(proposed_size):
            return False, f"Insufficient capital: need {proposed_size:.2f}"

        return True, ""

    # ------------------------------------------------------------------ #
    #  Post-trade / monitoring updates                                     #
    # ------------------------------------------------------------------ #

    def update_on_close(self, pnl: float) -> None:
        """
        Called after a trade closes. Checks for critical risk breaches.
        Activates kill switch if drawdown limit is breached.
        """
        drawdown = self._bankroll.current_drawdown
        if drawdown >= self._settings.max_drawdown:
            self._kill_switch.activate(f"Drawdown {drawdown:.2%} post-trade")
            return

        # Drawdown warning at 75% of limit
        if drawdown >= self._settings.max_drawdown * 0.75:
            log_event(
                logger,
                Events.DRAWDOWN_WARNING,
                level="WARNING",
                drawdown=f"{drawdown:.2%}",
                limit=f"{self._settings.max_drawdown:.2%}",
            )

    def update_regime(self, price: float) -> float:
        """
        Update regime detector with latest price. Returns risk multiplier.
        """
        self._regime.update(price)
        return self._regime.risk_multiplier

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #

    def get_state(self, open_positions: list[Position]) -> RiskState:
        """Build a snapshot of current risk state."""
        return RiskState(
            daily_pnl=self._bankroll.daily_pnl,
            daily_pnl_pct=self._bankroll.daily_pnl_pct,
            peak_equity=self._bankroll._peak_equity,
            current_equity=self._bankroll.total_equity,
            current_drawdown=self._bankroll.current_drawdown,
            open_position_count=len(open_positions),
            total_exposure=sum(p.notional_value for p in open_positions),
            correlated_exposure=self._compute_correlated_exposure(
                symbol="", open_positions=open_positions
            ),
            regime=self._regime.current_regime,
            risk_multiplier=self._regime.risk_multiplier,
            kill_switch_active=self._kill_switch.is_active,
            last_updated=datetime.utcnow(),
        )

    def get_risk_events(self, limit: int = 50) -> list[RiskEvent]:
        """Return the most recent risk events."""
        return self._risk_events[-limit:]

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _record_event(
        self,
        event_type: RiskEventType,
        description: str,
        symbol: Optional[str] = None,
        value: Optional[float] = None,
    ) -> None:
        """Record a risk event and send an alert."""
        event = RiskEvent(
            event_type=event_type,
            description=description,
            symbol=symbol,
            value=value,
        )
        self._risk_events.append(event)

        log_event(logger, Events.RISK_LIMIT_HIT, level="WARNING",
                  risk_event=event_type.value, description=description)

        try:
            get_alert_manager().send(
                event_type=Events.RISK_LIMIT_HIT,
                message=description,
                level="WARNING",
                event=event_type.value,
            )
        except Exception as e:
            logger.debug("Alert send failed: %s", e)

    def _compute_correlated_exposure(
        self,
        symbol: str,
        open_positions: list[Position],
    ) -> float:
        """
        Compute total correlated exposure as fraction of equity.

        Simplified: treats same-asset positions as perfectly correlated (1.0)
        and positions in different symbols as 0.5 correlated.
        A production system would use a real correlation matrix.
        """
        if not open_positions:
            return 0.0

        equity = max(self._bankroll.total_equity, 1)
        exposure = 0.0

        for pos in open_positions:
            notional_fraction = pos.notional_value / equity
            if pos.symbol == symbol:
                exposure += notional_fraction * 1.0  # Perfectly correlated
            else:
                exposure += notional_fraction * 0.5  # Partially correlated

        return exposure
