"""
app/models/signal.py — Trading signal models.

A Signal represents a detected opportunity before execution.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
import uuid


class SignalType(str, Enum):
    MISPRICING = "mispricing"
    ORDERBOOK_IMBALANCE = "orderbook_imbalance"
    CROSS_MARKET = "cross_market"
    IMPLIED_PROB_MISMATCH = "implied_prob_mismatch"
    LIQUIDITY_VACUUM = "liquidity_vacuum"


class SignalDirection(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Signal(BaseModel):
    """
    A trading signal produced by a strategy.

    Contains all information needed by the EV engine to evaluate
    whether to execute the opportunity.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strategy: str
    signal_type: SignalType
    symbol: str
    exchange: str = "mock"
    direction: SignalDirection

    # Price levels
    entry_price: float
    fair_value: float          # Strategy's estimate of fair value
    target_price: Optional[float] = None
    stop_price: Optional[float] = None

    # Edge metrics
    raw_edge: float = 0.0      # (fair_value - entry_price) / entry_price
    win_probability: float = 0.0
    expected_value: float = 0.0

    # Confidence
    confidence: float = 1.0   # Bayesian confidence weight [0, 1]
    num_observations: int = 1  # Sample size for Bayesian estimation

    # Timing
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None

    # Score (from opportunity scorer)
    score: float = 0.0

    # Context
    notes: str = ""

    @property
    def age_seconds(self) -> float:
        """Seconds since signal was created."""
        return (datetime.utcnow() - self.created_at).total_seconds()

    @property
    def is_expired(self) -> bool:
        """True if the signal has exceeded its expiry time."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
