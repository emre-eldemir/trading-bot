"""
app/config.py — Central configuration loader.

Loads config.yaml and merges with environment variables from .env.
All components import settings from here.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

# Load .env file if it exists (for local development)
load_dotenv()

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def _load_yaml() -> dict[str, Any]:
    """Load config.yaml from the project root."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml()


class TradingConfig(BaseSettings):
    """Top-level application settings — merged from YAML + env vars."""

    # ---- Trading mode ----
    simulation_mode: bool = _yaml.get("trading", {}).get("simulation_mode", True)
    live_trading: bool = _yaml.get("trading", {}).get("live_trading", False)
    use_leverage: bool = _yaml.get("trading", {}).get("use_leverage", False)

    # ---- Market ----
    exchange: str = _yaml.get("market", {}).get("exchange", "mock")
    symbols: list[str] = _yaml.get("market", {}).get("symbols", ["BTC/USDT"])
    polling_interval: float = _yaml.get("market", {}).get("polling_interval", 5)
    min_polling_interval: float = _yaml.get("market", {}).get("min_polling_interval", 1)
    max_polling_interval: float = _yaml.get("market", {}).get("max_polling_interval", 30)
    high_volatility_threshold: float = _yaml.get("market", {}).get("high_volatility_threshold", 0.80)
    low_volatility_threshold: float = _yaml.get("market", {}).get("low_volatility_threshold", 0.20)

    # ---- Fees ----
    maker_fee: float = _yaml.get("fees", {}).get("maker_fee", 0.0002)
    taker_fee: float = _yaml.get("fees", {}).get("taker_fee", 0.0005)
    prefer_maker: bool = _yaml.get("fees", {}).get("prefer_maker", True)

    # ---- EV ----
    min_edge: float = _yaml.get("ev", {}).get("min_edge", 0.005)
    min_ev: float = _yaml.get("ev", {}).get("min_ev", 0.003)
    signal_decay_half_life: float = _yaml.get("ev", {}).get("signal_decay_half_life", 60)
    slippage_buffer: float = _yaml.get("ev", {}).get("slippage_buffer", 0.001)
    execution_delay: float = _yaml.get("ev", {}).get("execution_delay", 0.5)
    min_confidence: float = _yaml.get("ev", {}).get("min_confidence", 0.6)

    # ---- Kelly ----
    kelly_fraction: float = _yaml.get("kelly", {}).get("fraction", 0.25)
    correlation_threshold: float = _yaml.get("kelly", {}).get("correlation_threshold", 0.70)
    min_position_fraction: float = _yaml.get("kelly", {}).get("min_position_fraction", 0.005)
    max_position_fraction: float = _yaml.get("kelly", {}).get("max_position_fraction", 0.10)
    drawdown_reduction_thresholds: list[dict] = _yaml.get("kelly", {}).get(
        "drawdown_reduction_thresholds", []
    )

    # ---- Bankroll ----
    active_capital_ratio: float = _yaml.get("bankroll", {}).get("active_capital_ratio", 0.50)
    min_active_capital: float = _yaml.get("bankroll", {}).get("min_active_capital", 100.0)
    starting_bankroll: float = _yaml.get("bankroll", {}).get("starting_bankroll", 10000.0)

    # ---- Risk ----
    daily_max_loss: float = _yaml.get("risk", {}).get("daily_max_loss", 0.02)
    max_drawdown: float = _yaml.get("risk", {}).get("max_drawdown", 0.15)
    max_open_positions: int = _yaml.get("risk", {}).get("max_open_positions", 5)
    max_single_trade_risk: float = _yaml.get("risk", {}).get("max_single_trade_risk", 0.02)
    max_correlated_exposure: float = _yaml.get("risk", {}).get("max_correlated_exposure", 0.20)
    high_vol_risk_multiplier: float = _yaml.get("risk", {}).get("high_vol_risk_multiplier", 0.50)
    low_vol_risk_multiplier: float = _yaml.get("risk", {}).get("low_vol_risk_multiplier", 1.00)

    # ---- Execution ----
    order_timeout: int = _yaml.get("execution", {}).get("order_timeout", 30)
    max_retries: int = _yaml.get("execution", {}).get("max_retries", 3)
    retry_delay: float = _yaml.get("execution", {}).get("retry_delay", 1.0)
    twap_slices: int = _yaml.get("execution", {}).get("twap_slices", 5)
    twap_interval: float = _yaml.get("execution", {}).get("twap_interval", 10)
    large_order_threshold: float = _yaml.get("execution", {}).get("large_order_threshold", 0.05)

    # ---- Scoring ----
    ev_weight: float = _yaml.get("scoring", {}).get("ev_weight", 0.40)
    liquidity_weight: float = _yaml.get("scoring", {}).get("liquidity_weight", 0.25)
    confidence_weight: float = _yaml.get("scoring", {}).get("confidence_weight", 0.20)
    freshness_weight: float = _yaml.get("scoring", {}).get("freshness_weight", 0.15)
    min_score: float = _yaml.get("scoring", {}).get("min_score", 0.50)

    # ---- Database ----
    database_url: str = os.getenv(
        "DATABASE_URL",
        _yaml.get("database", {}).get("url", "sqlite:///./data/trading_bot.db"),
    )

    # ---- Logging ----
    log_level: str = os.getenv("LOG_LEVEL", _yaml.get("logging", {}).get("level", "INFO"))
    log_file: str = _yaml.get("logging", {}).get("file", "logs/trading_bot.log")

    # ---- API ----
    api_host: str = _yaml.get("api", {}).get("host", "0.0.0.0")
    api_port: int = _yaml.get("api", {}).get("port", 8000)

    # ---- Alerting ----
    alerting_enabled: bool = _yaml.get("alerting", {}).get("enabled", False)
    min_alert_interval: int = _yaml.get("alerting", {}).get("min_alert_interval", 60)
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    discord_webhook_url: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    # ---- Exchange credentials ----
    exchange_api_key: str = os.getenv("EXCHANGE_API_KEY", "")
    exchange_api_secret: str = os.getenv("EXCHANGE_API_SECRET", "")

    @field_validator("kelly_fraction")
    @classmethod
    def validate_kelly_fraction(cls, v: float) -> float:
        """Enforce sensible Kelly fraction bounds."""
        if not 0.0 < v <= 1.0:
            raise ValueError("kelly_fraction must be in (0, 1]")
        return v

    @field_validator("max_drawdown")
    @classmethod
    def validate_max_drawdown(cls, v: float) -> float:
        """Enforce positive drawdown limit."""
        if not 0.0 < v < 1.0:
            raise ValueError("max_drawdown must be in (0, 1)")
        return v

    model_config = {"env_prefix": "", "case_sensitive": False}


@lru_cache(maxsize=1)
def get_settings() -> TradingConfig:
    """Return cached singleton settings instance."""
    return TradingConfig()
