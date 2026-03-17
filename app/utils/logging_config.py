"""
app/utils/logging_config.py — Structured logging setup.

Configures both console and file handlers with consistent formatting.
Event types are standardised for easy filtering and alerting.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any


# Canonical event type constants — use these in log calls for consistency
class Events:
    SIGNAL_FOUND = "signal_found"
    TRADE_OPENED = "trade_opened"
    TRADE_CLOSED = "trade_closed"
    TRADE_REJECTED = "trade_rejected"
    RISK_LIMIT_HIT = "risk_limit_hit"
    FEED_ERROR = "feed_error"
    SHUTDOWN_TRIGGERED = "shutdown_triggered"
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    ORDER_TIMEOUT = "order_timeout"
    PARTIAL_FILL = "partial_fill"
    DRAWDOWN_WARNING = "drawdown_warning"
    REGIME_CHANGE = "regime_change"
    BACKTEST_COMPLETE = "backtest_complete"


def setup_logging(
    level: str = "INFO",
    log_file: str = "logs/trading_bot.log",
    max_bytes: int = 10_485_760,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Configure root logger with console + rotating file handlers.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Path to the log file.
        max_bytes: Max log file size before rotation.
        backup_count: Number of backup files to keep.

    Returns:
        Root logger instance.
    """
    # Ensure log directory exists
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    log_format = logging.Formatter(
        fmt="%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicate output
    root_logger.handlers.clear()

    # Console handler — writes to stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    root_logger.addHandler(console_handler)

    # Rotating file handler — prevents unbounded disk usage
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_format)
    root_logger.addHandler(file_handler)

    # Silence noisy third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call after setup_logging() has been called."""
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    event_type: str,
    level: str = "INFO",
    **kwargs: Any,
) -> None:
    """
    Log a structured event with key=value pairs.

    Example:
        log_event(logger, Events.SIGNAL_FOUND, symbol="BTC/USDT", ev=0.012)
    """
    fields = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    message = f"event={event_type} | {fields}" if fields else f"event={event_type}"
    getattr(logger, level.lower(), logger.info)(message)
