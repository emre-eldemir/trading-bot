"""
app/risk/kill_switch.py — Emergency kill switch.

When activated, prevents any new trades and initiates safe shutdown.
The kill switch can be triggered by:
- Exceeding max drawdown
- Manual activation (operator)
- API/feed failure
- Automated risk rule breach
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.utils.logging_config import Events, log_event
from app.utils.alerting import get_alert_manager

logger = logging.getLogger(__name__)


class KillSwitch:
    """
    Global kill switch — a safety circuit breaker for the trading system.

    Once activated, the kill switch CANNOT be automatically reset.
    It requires explicit manual reset (to prevent accidental restart).
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._activation_reason: Optional[str] = None
        self._activated_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        """True if the kill switch has been triggered."""
        return self._active

    @property
    def reason(self) -> Optional[str]:
        return self._activation_reason

    @property
    def activated_at(self) -> Optional[datetime]:
        return self._activated_at

    def activate(self, reason: str) -> None:
        """
        Activate the kill switch.

        Sends alert and logs critical event.
        All trading functions should check is_active before proceeding.
        """
        if self._active:
            return  # Already active

        self._active = True
        self._activation_reason = reason
        self._activated_at = datetime.utcnow()

        log_event(
            logger,
            Events.KILL_SWITCH_ACTIVATED,
            level="CRITICAL",
            reason=reason,
            timestamp=self._activated_at.isoformat(),
        )

        # Send external alert
        try:
            get_alert_manager().send(
                event_type=Events.KILL_SWITCH_ACTIVATED,
                message=f"Kill switch activated: {reason}",
                level="CRITICAL",
                reason=reason,
            )
        except Exception as e:
            logger.error("Failed to send kill switch alert: %s", e)

    def reset(self, operator_confirmed: bool = False) -> bool:
        """
        Reset the kill switch.

        Requires explicit operator confirmation — prevents accidental reset.
        Returns True if reset was successful.
        """
        if not operator_confirmed:
            logger.warning("Kill switch reset requires operator_confirmed=True")
            return False

        logger.warning(
            "Kill switch RESET by operator | was active for %.0f seconds",
            (datetime.utcnow() - self._activated_at).total_seconds()
            if self._activated_at else 0,
        )
        self._active = False
        self._activation_reason = None
        self._activated_at = None
        return True

    def check(self) -> None:
        """Raise RuntimeError if kill switch is active. Use as a guard."""
        if self._active:
            raise RuntimeError(f"Kill switch active: {self._activation_reason}")

    def status(self) -> dict:
        return {
            "active": self._active,
            "reason": self._activation_reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
        }
