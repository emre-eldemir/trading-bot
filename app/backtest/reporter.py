"""
app/backtest/reporter.py — Backtest performance reporter.

Generates:
- Console summary
- CSV trade log
- Equity curve chart (matplotlib)
- JSON metrics dump
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.backtest.backtester import BacktestResult

logger = logging.getLogger(__name__)

_REPORTS_DIR = Path("data/reports")


def generate_report(result: BacktestResult, report_name: str = "backtest") -> Path:
    """
    Generate a full backtest report.

    Creates:
    - {report_name}_summary.json
    - {report_name}_trades.csv
    - {report_name}_equity_curve.png (if matplotlib available)

    Returns the reports directory path.
    """
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    prefix = _REPORTS_DIR / f"{report_name}_{timestamp}"

    _write_summary(result, Path(f"{prefix}_summary.json"))
    _write_trades_csv(result, Path(f"{prefix}_trades.csv"))
    _write_equity_chart(result, Path(f"{prefix}_equity_curve.png"))

    logger.info("Report generated: %s", prefix)
    return _REPORTS_DIR


def _write_summary(result: BacktestResult, path: Path) -> None:
    """Write JSON summary of backtest results."""
    summary = {
        "start_equity": result.start_equity,
        "end_equity": result.end_equity,
        "return_pct": round(result.return_pct * 100, 4),
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate_pct": round(result.win_rate * 100, 2),
        "total_pnl": round(result.total_pnl, 4),
        "total_fees": round(result.total_fees, 4),
        "total_slippage": round(result.total_slippage, 4),
        "net_pnl": round(result.net_pnl, 4),
        "max_drawdown_pct": round(result.max_drawdown * 100, 2),
        "sharpe_ratio": round(result.sharpe_ratio, 4),
        "expectancy": round(result.expectancy, 4),
        "avg_trade_duration_s": round(result.avg_trade_duration, 1),
        "best_trade": round(result.best_trade, 4),
        "worst_trade": round(result.worst_trade, 4),
        "start_time": result.start_time.isoformat() if result.start_time else None,
        "end_time": result.end_time.isoformat() if result.end_time else None,
    }
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Summary written: %s", path)

    # Also print to console
    print("\n" + "=" * 60)
    print("  BACKTEST RESULTS")
    print("=" * 60)
    for key, value in summary.items():
        print(f"  {key:<30} {value}")
    print("=" * 60 + "\n")


def _write_trades_csv(result: BacktestResult, path: Path) -> None:
    """Write per-trade CSV log."""
    if not result.trades:
        return
    fieldnames = [
        "id", "symbol", "direction", "entry_price", "exit_price",
        "quantity", "gross_pnl", "fees", "slippage", "net_pnl",
        "strategy", "opened_at", "closed_at", "hold_duration_seconds",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for trade in result.trades:
            writer.writerow({
                "id": trade.id,
                "symbol": trade.symbol,
                "direction": trade.direction,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "quantity": trade.quantity,
                "gross_pnl": round(trade.gross_pnl, 6),
                "fees": round(trade.fees, 6),
                "slippage": round(trade.slippage, 6),
                "net_pnl": round(trade.net_pnl, 6),
                "strategy": trade.strategy,
                "opened_at": trade.opened_at.isoformat() if trade.opened_at else "",
                "closed_at": trade.closed_at.isoformat() if trade.closed_at else "",
                "hold_duration_seconds": round(trade.hold_duration_seconds, 1),
            })
    logger.info("Trades CSV written: %s", path)


def _write_equity_chart(result: BacktestResult, path: Path) -> None:
    """Generate equity curve chart using matplotlib."""
    if not result.equity_curve:
        return
    try:
        import matplotlib
        matplotlib.use("Agg")  # Non-interactive backend for server environments
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

        # Equity curve
        ax1.plot(result.equity_curve, linewidth=1.5, color="steelblue")
        ax1.axhline(y=result.start_equity, color="gray", linestyle="--", alpha=0.5)
        ax1.set_title("Equity Curve")
        ax1.set_ylabel("Portfolio Value ($)")
        ax1.grid(True, alpha=0.3)

        # Per-trade PnL
        if result.trades:
            pnls = [t.net_pnl for t in result.trades]
            colours = ["green" if p > 0 else "red" for p in pnls]
            ax2.bar(range(len(pnls)), pnls, color=colours, alpha=0.7)
            ax2.axhline(y=0, color="black", linewidth=0.8)
            ax2.set_title("Per-Trade Net PnL")
            ax2.set_ylabel("PnL ($)")
            ax2.set_xlabel("Trade #")
            ax2.grid(True, alpha=0.3)

        plt.suptitle(
            f"Backtest: {result.total_trades} trades | "
            f"Return {result.return_pct:.1%} | "
            f"MaxDD {result.max_drawdown:.1%} | "
            f"Sharpe {result.sharpe_ratio:.2f}",
            fontsize=11,
        )
        plt.tight_layout()
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info("Equity chart saved: %s", path)

    except ImportError:
        logger.warning("matplotlib not installed — skipping equity chart")
    except Exception as e:
        logger.warning("Chart generation failed: %s", e)
