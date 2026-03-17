"""
app/backtest/simulator.py — Paper trading live simulation.

Runs the full strategy pipeline against live market data in paper mode.
No real orders are sent. All trades are simulated.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.config import TradingConfig, get_settings
from app.execution.execution_engine import ExecutionEngine
from app.models.market import MarketMetrics
from app.models.signal import Signal
from app.risk.risk_manager import RiskManager
from app.services.ev_engine import EVEngine
from app.services.market_scanner import MarketScanner
from app.services.opportunity_scorer import OpportunityScorer
from app.strategies.base_strategy import BaseStrategy
from app.utils.logging_config import Events, log_event

logger = logging.getLogger(__name__)


class PaperTrader:
    """
    Live paper trading simulator.

    Runs strategies against live market data, evaluates EV, scores
    opportunities, and simulates trades — all without real order submission.
    """

    def __init__(
        self,
        scanner: MarketScanner,
        strategies: list[BaseStrategy],
        ev_engine: EVEngine,
        scorer: OpportunityScorer,
        execution: ExecutionEngine,
        risk_manager: RiskManager,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._scanner = scanner
        self._strategies = strategies
        self._ev_engine = ev_engine
        self._scorer = scorer
        self._execution = execution
        self._risk = risk_manager
        self._settings = settings or get_settings()
        self._running = False

        # Register scanner callback to trigger strategy evaluation
        self._scanner.register_callback(self._on_new_metrics)

    def _on_new_metrics(self, metrics: MarketMetrics) -> None:
        """Called each time new market metrics are computed by the scanner."""
        asyncio.create_task(self._process_metrics(metrics))

    async def _process_metrics(self, metrics: MarketMetrics) -> None:
        """Full pipeline: metrics → signals → EV → scoring → execution."""
        # Update regime detector
        if metrics.mid_price > 0:
            self._risk.update_regime(metrics.mid_price)

        # Update position prices
        self._execution.update_position_prices(metrics.symbol, metrics.mid_price)

        # 1. Generate raw signals from all enabled strategies
        all_signals: list[Signal] = []
        for strategy in self._strategies:
            if not strategy.is_enabled:
                continue
            try:
                signals = strategy.generate_signals(metrics)
                all_signals.extend(signals)
            except Exception as e:
                logger.warning("Strategy %s error: %s", strategy.name, e)

        if not all_signals:
            return

        # 2. EV evaluation
        metrics_map = self._scanner.get_all_metrics()
        evaluated = self._ev_engine.batch_evaluate(all_signals, metrics_map)

        if not evaluated:
            return

        # 3. Score and rank opportunities
        ranked = self._scorer.filter_and_rank(evaluated, metrics_map)

        # 4. Execute top-scoring opportunities
        for signal, score in ranked[:3]:  # Execute at most 3 signals per cycle
            signal = signal.model_copy(update={"score": score})
            log_event(
                logger, Events.SIGNAL_FOUND,
                signal_id=signal.id[:8],
                symbol=signal.symbol,
                strategy=signal.strategy,
                ev=f"{signal.expected_value:.6f}",
                score=f"{score:.3f}",
            )
            position = await self._execution.execute_signal(signal)
            if position:
                logger.info(
                    "Position opened: %s %s @%.4f",
                    position.side.value, position.symbol, position.entry_price,
                )

    async def run(self) -> None:
        """Start the paper trading loop."""
        self._running = True
        logger.info("Paper trader started — simulation_mode=%s", self._settings.simulation_mode)
        await self._scanner.start()

    def stop(self) -> None:
        """Stop the paper trading loop."""
        self._scanner.stop()
        self._running = False
