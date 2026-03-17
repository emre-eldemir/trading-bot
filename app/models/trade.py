"""
app/models/trade.py — Trade and order models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
import uuid


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    POST_ONLY = "post_only"


class OrderStatus(str, Enum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Order(BaseModel):
    """Represents a single order sent (or simulated) to an exchange."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    exchange_order_id: Optional[str] = None
    symbol: str
    exchange: str = "mock"
    side: OrderSide
    order_type: OrderType = OrderType.LIMIT
    quantity: float
    price: Optional[float] = None    # None for market orders
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    average_fill_price: Optional[float] = None
    fee_paid: float = 0.0
    signal_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    filled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    notes: str = ""


class Trade(BaseModel):
    """
    A completed round-trip trade (entry + exit).
    Created when a position is opened and closed.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    exchange: str = "mock"
    direction: str   # "buy" or "sell"
    entry_order_id: str
    exit_order_id: Optional[str] = None

    # Prices
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float

    # Financial result
    gross_pnl: float = 0.0
    fees: float = 0.0
    slippage: float = 0.0
    net_pnl: float = 0.0

    # Metadata
    strategy: str = ""
    signal_id: Optional[str] = None
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    hold_duration_seconds: float = 0.0

    @property
    def is_closed(self) -> bool:
        return self.exit_price is not None and self.closed_at is not None
