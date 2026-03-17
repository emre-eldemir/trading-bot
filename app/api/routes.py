"""
app/api/routes.py — FastAPI route definitions.

Endpoints:
  GET /             — Dashboard home
  GET /api/status   — System status JSON
  GET /api/metrics  — Market metrics
  GET /api/positions — Open positions
  GET /api/trades   — Recent trades
  GET /api/signals  — Recent signals
  GET /api/bankroll — Bankroll status
  GET /api/risk     — Risk state
  POST /api/kill-switch — Activate kill switch
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config import TradingConfig, get_settings
from app.db.database import get_db
from app.db.repositories import PnLRepository, SignalRepository, TradeRepository

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level references to running components
# These are set by main.py after initialisation
_execution_engine = None
_risk_manager = None
_bankroll = None
_kill_switch = None
_scanner = None


def set_runtime_refs(execution, risk_manager, bankroll, kill_switch, scanner) -> None:
    """Called by main.py to inject runtime component references into the API."""
    global _execution_engine, _risk_manager, _bankroll, _kill_switch, _scanner
    _execution_engine = execution
    _risk_manager = risk_manager
    _bankroll = bankroll
    _kill_switch = kill_switch
    _scanner = scanner


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> Any:
    """Serve the main dashboard."""
    settings: TradingConfig = get_settings()
    templates = getattr(request.app.state, "templates", None)

    if templates is None:
        # Fallback: return plain HTML if templates not found
        live_warning = ""
        if settings.live_trading:
            live_warning = (
                '<div style="background:red;color:white;padding:20px;font-size:24px;'
                'font-weight:bold;text-align:center;">⚠️ LIVE TRADING MODE IS ACTIVE ⚠️</div>'
            )
        return HTMLResponse(
            f"""<html><head><title>Trading Bot</title></head><body>
            {live_warning}
            <h1>Trading Bot Dashboard</h1>
            <p>Mode: {'LIVE' if settings.live_trading else 'PAPER'}</p>
            <p><a href="/api/status">System Status</a></p>
            <p><a href="/api/bankroll">Bankroll</a></p>
            <p><a href="/api/positions">Open Positions</a></p>
            <p><a href="/api/trades">Recent Trades</a></p>
            <p><a href="/api/risk">Risk State</a></p>
            </body></html>"""
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "live_trading": settings.live_trading,
            "simulation_mode": settings.simulation_mode,
        },
    )


@router.get("/api/status")
async def get_status() -> JSONResponse:
    """Return system status."""
    settings = get_settings()
    kill_status = _kill_switch.status() if _kill_switch else {"active": False}
    return JSONResponse({
        "status": "running",
        "simulation_mode": settings.simulation_mode,
        "live_trading": settings.live_trading,
        "exchange": settings.exchange,
        "symbols": settings.symbols,
        "kill_switch": kill_status,
    })


@router.get("/api/bankroll")
async def get_bankroll() -> JSONResponse:
    """Return bankroll status."""
    if _bankroll is None:
        return JSONResponse({"error": "Bankroll not initialised"}, status_code=503)
    return JSONResponse(_bankroll.get_summary())


@router.get("/api/positions")
async def get_positions() -> JSONResponse:
    """Return open positions."""
    if _execution_engine is None:
        return JSONResponse([])
    positions = [
        {
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side.value,
            "quantity": p.quantity,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "unrealised_pnl": round(p.unrealised_pnl, 4),
            "unrealised_pnl_pct": round(p.unrealised_pnl_pct, 4),
            "strategy": p.strategy,
            "opened_at": p.opened_at.isoformat(),
        }
        for p in _execution_engine.open_positions
    ]
    return JSONResponse(positions)


@router.get("/api/trades")
async def get_trades(db: Session = Depends(get_db)) -> JSONResponse:
    """Return recent trades from database."""
    repo = TradeRepository(db)
    trades = repo.get_recent(limit=50)
    return JSONResponse([
        {
            "id": t.id,
            "symbol": t.symbol,
            "direction": t.direction,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "net_pnl": round(t.net_pnl, 4),
            "fees": round(t.fees, 4),
            "strategy": t.strategy,
            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        }
        for t in trades
    ])


@router.get("/api/signals")
async def get_signals(db: Session = Depends(get_db)) -> JSONResponse:
    """Return recent signals from database."""
    repo = SignalRepository(db)
    signals = repo.get_recent(limit=50)
    return JSONResponse([
        {
            "id": s.id,
            "strategy": s.strategy,
            "symbol": s.symbol,
            "direction": s.direction,
            "entry_price": s.entry_price,
            "raw_edge": round(s.raw_edge, 4),
            "expected_value": round(s.expected_value, 6),
            "confidence": round(s.confidence, 3),
            "score": round(s.score, 3),
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in signals
    ])


@router.get("/api/risk")
async def get_risk() -> JSONResponse:
    """Return current risk state."""
    if _risk_manager is None or _execution_engine is None:
        return JSONResponse({"error": "Risk manager not initialised"}, status_code=503)
    state = _risk_manager.get_state(_execution_engine.open_positions)
    return JSONResponse({
        "daily_pnl": round(state.daily_pnl, 4),
        "daily_pnl_pct": round(state.daily_pnl_pct, 4),
        "current_drawdown": round(state.current_drawdown, 4),
        "open_positions": state.open_position_count,
        "total_exposure": round(state.total_exposure, 4),
        "regime": state.regime.value,
        "risk_multiplier": state.risk_multiplier,
        "kill_switch_active": state.kill_switch_active,
    })


@router.get("/api/metrics")
async def get_metrics() -> JSONResponse:
    """Return latest market metrics from scanner."""
    if _scanner is None:
        return JSONResponse({})
    all_metrics = _scanner.get_all_metrics()
    return JSONResponse({
        symbol: {
            "mid_price": m.mid_price,
            "spread_pct": round(m.spread_pct, 6),
            "order_book_imbalance": round(m.order_book_imbalance, 4),
            "volatility": round(m.volatility, 4),
            "bid_depth": round(m.bid_depth, 4),
            "ask_depth": round(m.ask_depth, 4),
        }
        for symbol, m in all_metrics.items()
    })


@router.post("/api/kill-switch")
async def activate_kill_switch(reason: str = "Manual activation via API") -> JSONResponse:
    """Manually activate the kill switch."""
    if _kill_switch is None:
        raise HTTPException(status_code=503, detail="Kill switch not initialised")
    _kill_switch.activate(reason)
    logger.critical("Kill switch activated via API: %s", reason)
    return JSONResponse({"status": "activated", "reason": reason})
