"""
app/utils/alerting.py — Telegram and Discord webhook alerting.

Sends critical events to configured notification channels.
Includes rate limiting to prevent alert flooding.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class AlertManager:
    """
    Sends alerts via Telegram and/or Discord webhooks.

    Rate limiting: same alert type cannot fire more than once
    per min_alert_interval seconds.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        # Track last alert time per event type for rate limiting
        self._last_alert: dict[str, float] = defaultdict(float)

    def _is_rate_limited(self, event_type: str) -> bool:
        """Return True if alert should be suppressed due to rate limiting."""
        last = self._last_alert[event_type]
        now = time.time()
        if now - last < self._settings.min_alert_interval:
            return True
        self._last_alert[event_type] = now
        return False

    def send(
        self,
        event_type: str,
        message: str,
        level: str = "INFO",
        **kwargs: Any,
    ) -> None:
        """
        Send an alert if alerting is enabled and not rate-limited.

        Args:
            event_type: Canonical event type (e.g., Events.KILL_SWITCH_ACTIVATED).
            message: Human-readable alert message.
            level: Severity (INFO, WARNING, ERROR, CRITICAL).
            **kwargs: Additional context fields.
        """
        if not self._settings.alerting_enabled:
            return

        if self._is_rate_limited(event_type):
            logger.debug(f"Alert rate-limited: {event_type}")
            return

        # Build full message
        context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"[{level}] {event_type}: {message}"
        if context:
            full_message += f"\n{context}"

        self._send_telegram(full_message)
        self._send_discord(full_message, level)

    def _send_telegram(self, message: str) -> None:
        """Send message via Telegram Bot API."""
        token = self._settings.telegram_bot_token
        chat_id = self._settings.telegram_chat_id
        if not token or not chat_id:
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            response = httpx.post(
                url,
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=5.0,
            )
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Telegram alert failed: {e}")

    def _send_discord(self, message: str, level: str = "INFO") -> None:
        """Send message via Discord webhook."""
        webhook_url = self._settings.discord_webhook_url
        if not webhook_url:
            return

        # Map level to Discord embed colour
        colours = {"INFO": 3447003, "WARNING": 16776960, "ERROR": 15158332, "CRITICAL": 10038562}
        colour = colours.get(level.upper(), 3447003)

        payload = {
            "embeds": [
                {
                    "description": message,
                    "color": colour,
                }
            ]
        }
        try:
            response = httpx.post(webhook_url, json=payload, timeout=5.0)
            response.raise_for_status()
        except Exception as e:
            logger.warning(f"Discord alert failed: {e}")


# Module-level singleton
_alert_manager: AlertManager | None = None


def get_alert_manager() -> AlertManager:
    """Return the global AlertManager singleton."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
