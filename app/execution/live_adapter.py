"""
app/execution/live_adapter.py — Live exchange adapter interface stub.

This file provides the skeleton for connecting to a real exchange.
It is NOT functional by default — you must implement it for your specific exchange.

WARNING: Do NOT use live trading until:
- All risk rules are tested and verified
- The kill switch has been validated
- Position sizing has been reviewed
- The system has run in paper mode for at least 2 weeks
"""

from __future__ import annotations

import logging
from typing import Optional

from app.config import TradingConfig, get_settings
from app.execution.base_adapter import BaseAdapter
from app.models.market import OrderBook, Ticker
from app.models.trade import Order

logger = logging.getLogger(__name__)


class LiveAdapter(BaseAdapter):
    """
    Live exchange adapter — STUB. Implement for your exchange.

    To implement:
    1. Install the exchange library (e.g., ccxt, python-binance)
    2. Implement each abstract method below
    3. Add error handling and retry logic
    4. Test EXTENSIVELY in paper mode before going live
    """

    def __init__(self, settings: Optional[TradingConfig] = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.live_trading:
            raise RuntimeError(
                "LiveAdapter instantiated but live_trading=False. "
                "Set live_trading=true in config.yaml to enable."
            )
        if not self._settings.exchange_api_key:
            raise RuntimeError("EXCHANGE_API_KEY not set in environment.")
        logger.warning("LiveAdapter initialised — LIVE TRADING MODE ACTIVE")

    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        """Implement: fetch L2 order book from exchange API."""
        raise NotImplementedError("Implement fetch_order_book for your exchange.")

    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Implement: fetch ticker from exchange API."""
        raise NotImplementedError("Implement fetch_ticker for your exchange.")

    async def submit_order(self, order: Order) -> Order:
        """Implement: submit order to exchange API."""
        raise NotImplementedError("Implement submit_order for your exchange.")

    async def cancel_order(self, order: Order) -> Order:
        """Implement: cancel order via exchange API."""
        raise NotImplementedError("Implement cancel_order for your exchange.")

    async def get_order_status(self, order: Order) -> Order:
        """Implement: query order status from exchange API."""
        raise NotImplementedError("Implement get_order_status for your exchange.")

    async def get_balance(self) -> dict[str, float]:
        """Implement: fetch account balance from exchange API."""
        raise NotImplementedError("Implement get_balance for your exchange.")
