"""
app/main.py — Main entry point for the trading bot.

Initialises all components and starts the bot in the configured mode:
- Paper trading (default): simulation_mode=true
- Live trading: requires explicit live_trading=true in config

Usage:
    python -m app.main               # Paper trading
    python -m app.main --backtest    # Run backtest
    python -m app.main --api         # API server only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from app.config import get_settings
from app.utils.logging_config import Events, log_event, setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EV-based Trading Bot")
    parser.add_argument("--backtest", action="store_true", help="Run backtest mode")
    parser.add_argument("--api", action="store_true", help="Run API server only")
    parser.add_argument("--paper", action="store_true", help="Run paper trading (default)")
    return parser.parse_args()


async def run_paper_trading(settings) -> None:
    """Run the paper trading / live simulation pipeline."""
    from app.execution.mock_adapter import MockAdapter
    from app.execution.order_manager import OrderManager
    from app.execution.execution_engine import ExecutionEngine
    from app.risk.kill_switch import KillSwitch
    from app.risk.regime_detector import RegimeDetector
    from app.risk.risk_manager import RiskManager
    from app.services.bankroll_manager import BankrollManager
    from app.services.ev_engine import EVEngine
    from app.services.market_scanner import MarketScanner
    from app.services.opportunity_scorer import OpportunityScorer
    from app.services.position_sizer import PositionSizer
    from app.strategies.mispricing_strategy import MispricingStrategy
    from app.strategies.orderbook_imbalance_strategy import OrderBookImbalanceStrategy
    from app.strategies.cross_market_strategy import CrossMarketStrategy
    from app.backtest.simulator import PaperTrader
    from app.db.database import init_db
    from app.api.routes import set_runtime_refs

    logger = logging.getLogger(__name__)

    # Initialise database
    Path("data").mkdir(exist_ok=True)
    init_db()

    # Build component tree
    adapter = MockAdapter(settings)
    scanner = MarketScanner(adapter, settings)

    bankroll = BankrollManager(settings)
    kill_switch = KillSwitch()
    regime_detector = RegimeDetector(settings=settings)
    risk_manager = RiskManager(bankroll, kill_switch, regime_detector, settings)

    ev_engine = EVEngine(settings)
    scorer = OpportunityScorer(settings)
    sizer = PositionSizer(bankroll, settings)
    order_manager = OrderManager(adapter, settings)
    execution = ExecutionEngine(order_manager, sizer, bankroll, risk_manager, kill_switch, settings)

    strategies = [
        MispricingStrategy(settings),
        OrderBookImbalanceStrategy(settings=settings),
        CrossMarketStrategy(settings=settings),
    ]

    paper_trader = PaperTrader(
        scanner=scanner,
        strategies=strategies,
        ev_engine=ev_engine,
        scorer=scorer,
        execution=execution,
        risk_manager=risk_manager,
        settings=settings,
    )

    # Inject references into API layer
    set_runtime_refs(execution, risk_manager, bankroll, kill_switch, scanner)

    log_event(logger, Events.TRADE_OPENED, level="INFO", mode="paper_trading_started")
    logger.info("="*60)
    logger.info("  TRADING BOT STARTING — PAPER TRADING MODE")
    logger.info("  Bankroll: $%.2f", settings.starting_bankroll)
    logger.info("  Symbols: %s", settings.symbols)
    logger.info("  Strategies: %d active", len(strategies))
    logger.info("="*60)

    try:
        await paper_trader.run()
    except KeyboardInterrupt:
        log_event(logger, Events.SHUTDOWN_TRIGGERED, reason="KeyboardInterrupt")
        scanner.stop()
        logger.info("Graceful shutdown complete.")


def run_backtest(settings) -> None:
    """Run historical backtest."""
    import json
    from datetime import datetime, timedelta
    from app.models.market import MarketMetrics
    from app.strategies.mispricing_strategy import MispricingStrategy
    from app.strategies.orderbook_imbalance_strategy import OrderBookImbalanceStrategy
    from app.services.ev_engine import EVEngine
    from app.backtest.backtester import Backtester
    from app.backtest.reporter import generate_report

    logger = logging.getLogger(__name__)
    logger.info("Starting backtest...")

    # Load or generate sample data
    sample_file = Path("data/sample_trades.json")
    snapshots: list[MarketMetrics] = []

    if sample_file.exists():
        with open(sample_file) as f:
            raw_data = json.load(f)
        for i, entry in enumerate(raw_data):
            snapshot = MarketMetrics(
                symbol=entry.get("symbol", "BTC/USDT"),
                mid_price=entry.get("price", 65000),
                best_bid=entry.get("price", 65000) * 0.9995,
                best_ask=entry.get("price", 65000) * 1.0005,
                spread=entry.get("price", 65000) * 0.001,
                spread_pct=0.001,
                bid_depth=entry.get("bid_qty", 10),
                ask_depth=entry.get("ask_qty", 10),
                order_book_imbalance=0.05,
                estimated_slippage_buy=0.0003,
                estimated_slippage_sell=0.0003,
                volume_24h=entry.get("volume", 1000),
                volatility=0.30,
                timestamp=datetime.utcnow() - timedelta(seconds=len(raw_data) - i),
            )
            snapshots.append(snapshot)
    else:
        # Generate synthetic snapshots for demo
        import random
        base_price = 65000.0
        for i in range(200):
            noise = random.gauss(0, base_price * 0.002)
            price = base_price + noise
            snapshots.append(MarketMetrics(
                symbol="BTC/USDT",
                mid_price=price,
                best_bid=price * 0.9995,
                best_ask=price * 1.0005,
                spread=price * 0.001,
                spread_pct=0.001,
                bid_depth=random.uniform(5, 50),
                ask_depth=random.uniform(5, 50),
                order_book_imbalance=random.uniform(-0.5, 0.5),
                estimated_slippage_buy=0.0003,
                estimated_slippage_sell=0.0003,
                volume_24h=random.uniform(500, 5000),
                volatility=0.30,
                timestamp=datetime.utcnow() - timedelta(seconds=200 - i),
            ))

    backtester = Backtester(
        strategies=[
            MispricingStrategy(settings),
            OrderBookImbalanceStrategy(settings=settings),
        ],
        ev_engine=EVEngine(settings),
        settings=settings,
    )

    result = backtester.run(snapshots, symbol="BTC/USDT")
    Path("data").mkdir(exist_ok=True)
    generate_report(result, report_name="backtest")


def run_api_server(settings) -> None:
    """Start the FastAPI dashboard server."""
    import uvicorn
    from app.api.app import create_app

    app = create_app()
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


def main() -> None:
    """Main entry point — parse args and start in appropriate mode."""
    settings = get_settings()

    # Set up logging
    setup_logging(
        level=settings.log_level,
        log_file=settings.log_file,
    )
    logger = logging.getLogger(__name__)

    # Safety check: warn loudly if live trading is enabled
    if settings.live_trading:
        logger.critical("=" * 60)
        logger.critical("  ⚠️  LIVE TRADING MODE IS ENABLED ⚠️")
        logger.critical("  Real orders WILL be sent to the exchange.")
        logger.critical("  Ensure you have reviewed all risk settings.")
        logger.critical("=" * 60)

    args = parse_args()

    if args.backtest:
        run_backtest(settings)
    elif args.api:
        run_api_server(settings)
    else:
        # Default: paper trading
        asyncio.run(run_paper_trading(settings))


if __name__ == "__main__":
    main()
