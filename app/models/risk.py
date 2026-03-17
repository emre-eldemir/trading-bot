"""
app/models/risk.py — Risk event and state models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
import uuid


class RiskEventType(str, Enum):
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    MAX_POSITIONS = "max_positions"
    SINGLE_TRADE_RISK = "single_trade_risk"
    CORRELATED_EXPOSURE = "correlated_exposure"
    KILL_SWITCH = "kill_switch"
    FEED_ERROR = "feed_error"
    API_FAILURE = "api_failure"
    REGIME_CHANGE = "regime_change"


class VolatilityRegime(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class RiskEvent(BaseModel):
    """Record of a risk rule being triggered."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: RiskEventType
    description: str
    symbol: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RiskState(BaseModel):
    """
    Current risk metrics snapshot.
    Updated continuously by the risk manager.
    """
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    current_drawdown: float = 0.0
    open_position_count: int = 0
    total_exposure: float = 0.0
    correlated_exposure: float = 0.0
    regime: VolatilityRegime = VolatilityRegime.NORMAL
    risk_multiplier: float = 1.0
    kill_switch_active: bool = False
    last_updated: datetime = Field(default_factory=datetime.utcnow)
