"""
app/execution/base_adapter.py — Abstract exchange adapter interface.

All exchange adapters (mock, live) implement this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.market import OrderBook, Ticker
from app.models.trade import Order, OrderStatus


class BaseAdapter(ABC):
    """
    Abstract base class for exchange connectivity adapters.

    Implement this interface to connect to any exchange.
    The mock adapter is the default for development and paper trading.
    """

    @abstractmethod
    async def fetch_order_book(self, symbol: str, depth: int = 20) -> OrderBook:
        """Fetch current order book for symbol."""
        ...

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Fetch current ticker for symbol."""
        ...

    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """
        Submit an order to the exchange.
        Returns the order with updated status and exchange_order_id.
        """
        ...

    @abstractmethod
    async def cancel_order(self, order: Order) -> Order:
        """Cancel an open order. Returns updated order with CANCELLED status."""
        ...

    @abstractmethod
    async def get_order_status(self, order: Order) -> Order:
        """Fetch current status of an order from the exchange."""
        ...

    @abstractmethod
    async def get_balance(self) -> dict[str, float]:
        """Return current account balances {currency: amount}."""
        ...
