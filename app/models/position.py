"""
app/models/position.py — Open position model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
import uuid


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"


class Position(BaseModel):
    """
    Represents a currently open position.

    Created when an order is filled, closed when an exit order fills.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    exchange: str = "mock"
    side: PositionSide
    quantity: float
    entry_price: float
    current_price: float = 0.0
    entry_order_id: str = ""
    signal_id: Optional[str] = None
    strategy: str = ""
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Risk parameters
    stop_price: Optional[float] = None
    target_price: Optional[float] = None

    # Risk budget allocated (fraction of bankroll)
    risk_budget: float = 0.0

    @property
    def unrealised_pnl(self) -> float:
        """Unrealised PnL based on current price."""
        if self.side == PositionSide.LONG:
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealised_pnl_pct(self) -> float:
        """Unrealised PnL as a percentage of entry value."""
        entry_value = self.entry_price * self.quantity
        if entry_value == 0:
            return 0.0
        return self.unrealised_pnl / entry_value

    @property
    def notional_value(self) -> float:
        """Current notional value of the position."""
        return self.current_price * self.quantity
