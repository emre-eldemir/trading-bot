"""
app/db/repositories.py — Repository pattern for database access.

All database reads/writes go through these repositories.
Business logic NEVER accesses the DB directly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.db.database import (
    PnLRecord,
    PositionRecord,
    RiskEventRecord,
    SignalRecord,
    TradeRecord,
)
from app.models.position import Position
from app.models.risk import RiskEvent
from app.models.signal import Signal
from app.models.trade import Trade

logger = logging.getLogger(__name__)


class TradeRepository:
    """CRUD operations for trade records."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save(self, trade: Trade) -> None:
        record = TradeRecord(
            id=trade.id,
            symbol=trade.symbol,
            exchange=trade.exchange,
            direction=trade.direction,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            quantity=trade.quantity,
            gross_pnl=trade.gross_pnl,
            fees=trade.fees,
            slippage=trade.slippage,
            net_pnl=trade.net_pnl,
            strategy=trade.strategy,
            signal_id=trade.signal_id,
            opened_at=trade.opened_at,
            closed_at=trade.closed_at,
            hold_duration_seconds=trade.hold_duration_seconds,
        )
        self._db.merge(record)
        self._db.commit()

    def get_recent(self, limit: int = 50) -> list[TradeRecord]:
        return (
            self._db.query(TradeRecord)
            .order_by(TradeRecord.opened_at.desc())
            .limit(limit)
            .all()
        )

    def get_by_symbol(self, symbol: str, limit: int = 100) -> list[TradeRecord]:
        return (
            self._db.query(TradeRecord)
            .filter(TradeRecord.symbol == symbol)
            .order_by(TradeRecord.opened_at.desc())
            .limit(limit)
            .all()
        )

    def count(self) -> int:
        return self._db.query(TradeRecord).count()


class SignalRepository:
    """CRUD operations for signal records."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save(self, signal: Signal) -> None:
        record = SignalRecord(
            id=signal.id,
            strategy=signal.strategy,
            signal_type=signal.signal_type.value,
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=signal.entry_price,
            fair_value=signal.fair_value,
            raw_edge=signal.raw_edge,
            win_probability=signal.win_probability,
            expected_value=signal.expected_value,
            confidence=signal.confidence,
            score=signal.score,
            created_at=signal.created_at,
            notes=signal.notes,
        )
        self._db.merge(record)
        self._db.commit()

    def get_recent(self, limit: int = 50) -> list[SignalRecord]:
        return (
            self._db.query(SignalRecord)
            .order_by(SignalRecord.created_at.desc())
            .limit(limit)
            .all()
        )


class PositionRepository:
    """CRUD operations for position records."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save(self, position: Position) -> None:
        record = PositionRecord(
            id=position.id,
            symbol=position.symbol,
            exchange=position.exchange,
            side=position.side.value,
            quantity=position.quantity,
            entry_price=position.entry_price,
            current_price=position.current_price,
            strategy=position.strategy,
            signal_id=position.signal_id,
            opened_at=position.opened_at,
            is_closed=False,
        )
        self._db.merge(record)
        self._db.commit()

    def get_open(self) -> list[PositionRecord]:
        return self._db.query(PositionRecord).filter(PositionRecord.is_closed == False).all()

    def close(self, position_id: str) -> None:
        self._db.query(PositionRecord).filter(
            PositionRecord.id == position_id
        ).update({"is_closed": True})
        self._db.commit()


class RiskEventRepository:
    """CRUD operations for risk events."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save(self, event: RiskEvent) -> None:
        record = RiskEventRecord(
            id=event.id,
            event_type=event.event_type.value,
            description=event.description,
            symbol=event.symbol,
            value=event.value,
            threshold=event.threshold,
            timestamp=event.timestamp,
        )
        self._db.add(record)
        self._db.commit()

    def get_recent(self, limit: int = 100) -> list[RiskEventRecord]:
        return (
            self._db.query(RiskEventRecord)
            .order_by(RiskEventRecord.timestamp.desc())
            .limit(limit)
            .all()
        )


class PnLRepository:
    """Daily PnL history."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def record_daily(self, equity: float, daily_pnl: float, drawdown: float) -> None:
        today = datetime.utcnow().date().isoformat()
        record = PnLRecord(
            date=today,
            equity=equity,
            daily_pnl=daily_pnl,
            drawdown=drawdown,
        )
        self._db.add(record)
        self._db.commit()

    def get_history(self, limit: int = 90) -> list[PnLRecord]:
        return (
            self._db.query(PnLRecord)
            .order_by(PnLRecord.recorded_at.desc())
            .limit(limit)
            .all()
        )
