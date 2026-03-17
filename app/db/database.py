"""
app/db/database.py — SQLite database setup using SQLAlchemy.

Uses SQLAlchemy Core with a simple declarative model for portability.
The repository pattern is used for all data access — no raw SQL in business logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Generator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # Required for SQLite + async
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# ORM Models (SQLAlchemy)
# ---------------------------------------------------------------------------

class TradeRecord(Base):
    """Persisted trade record."""
    __tablename__ = "trades"

    id = Column(String, primary_key=True)
    symbol = Column(String, index=True)
    exchange = Column(String)
    direction = Column(String)
    entry_price = Column(Float)
    exit_price = Column(Float, nullable=True)
    quantity = Column(Float)
    gross_pnl = Column(Float)
    fees = Column(Float)
    slippage = Column(Float)
    net_pnl = Column(Float)
    strategy = Column(String)
    signal_id = Column(String, nullable=True)
    opened_at = Column(DateTime)
    closed_at = Column(DateTime, nullable=True)
    hold_duration_seconds = Column(Float)


class SignalRecord(Base):
    """Persisted signal record."""
    __tablename__ = "signals"

    id = Column(String, primary_key=True)
    strategy = Column(String)
    signal_type = Column(String)
    symbol = Column(String, index=True)
    direction = Column(String)
    entry_price = Column(Float)
    fair_value = Column(Float)
    raw_edge = Column(Float)
    win_probability = Column(Float)
    expected_value = Column(Float)
    confidence = Column(Float)
    score = Column(Float)
    created_at = Column(DateTime)
    notes = Column(Text, default="")


class PositionRecord(Base):
    """Persisted position record."""
    __tablename__ = "positions"

    id = Column(String, primary_key=True)
    symbol = Column(String, index=True)
    exchange = Column(String)
    side = Column(String)
    quantity = Column(Float)
    entry_price = Column(Float)
    current_price = Column(Float)
    strategy = Column(String)
    signal_id = Column(String, nullable=True)
    opened_at = Column(DateTime)
    is_closed = Column(Boolean, default=False)


class RiskEventRecord(Base):
    """Persisted risk event record."""
    __tablename__ = "risk_events"

    id = Column(String, primary_key=True)
    event_type = Column(String, index=True)
    description = Column(Text)
    symbol = Column(String, nullable=True)
    value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    timestamp = Column(DateTime)


class PnLRecord(Base):
    """Daily PnL snapshot."""
    __tablename__ = "pnl_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, index=True)
    equity = Column(Float)
    daily_pnl = Column(Float)
    drawdown = Column(Float)
    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised: %s", settings.database_url)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a DB session and close it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
