"""
app/models/market.py — Market data models.

Pydantic models for order book snapshots, tickers, and market metrics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class OrderBookLevel(BaseModel):
    """A single price level in an order book."""
    price: float
    size: float


class OrderBook(BaseModel):
    """L2 order book snapshot."""
    symbol: str
    exchange: str = "mock"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bids: list[OrderBookLevel] = Field(default_factory=list)
    asks: list[OrderBookLevel] = Field(default_factory=list)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2.0
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_pct(self) -> Optional[float]:
        mid = self.mid_price
        spread = self.spread
        if mid and spread:
            return spread / mid
        return None

    def bid_depth(self, levels: int = 5) -> float:
        """Total bid-side depth for top N levels."""
        return sum(lvl.size for lvl in self.bids[:levels])

    def ask_depth(self, levels: int = 5) -> float:
        """Total ask-side depth for top N levels."""
        return sum(lvl.size for lvl in self.asks[:levels])

    def imbalance(self, levels: int = 5) -> float:
        """
        Order book imbalance: (bid_depth - ask_depth) / (bid_depth + ask_depth).
        Ranges from -1 (sell pressure) to +1 (buy pressure).
        """
        bid_d = self.bid_depth(levels)
        ask_d = self.ask_depth(levels)
        total = bid_d + ask_d
        if total == 0:
            return 0.0
        return (bid_d - ask_d) / total

    def as_ask_tuples(self) -> list[tuple[float, float]]:
        return [(lvl.price, lvl.size) for lvl in self.asks]

    def as_bid_tuples(self) -> list[tuple[float, float]]:
        return [(lvl.price, lvl.size) for lvl in self.bids]


class Ticker(BaseModel):
    """Current ticker data for a symbol."""
    symbol: str
    exchange: str = "mock"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume_24h: float = 0.0
    price_change_24h: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0


class MarketMetrics(BaseModel):
    """
    Aggregated metrics computed from order book + ticker data.
    Used by the EV engine and strategies.
    """
    symbol: str
    exchange: str = "mock"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Price
    mid_price: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    spread_pct: float = 0.0

    # Depth
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    order_book_imbalance: float = 0.0

    # Liquidity
    estimated_slippage_buy: float = 0.0
    estimated_slippage_sell: float = 0.0

    # Volume
    volume_24h: float = 0.0

    # Volatility (rolling)
    volatility: float = 0.0

    # Implied probability (for event/binary markets)
    implied_probability: Optional[float] = None

    # Fee-adjusted effective spread
    effective_spread_with_taker: float = 0.0
