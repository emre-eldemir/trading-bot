"""
app/services/market_scanner.py — Market data scanner.

Pulls order book and ticker data from the configured exchange adapter,
computes market metrics, and detects mispricing signals.

Key features:
- Adaptive polling: scan more frequently in high-volatility periods
- L2 order book depth analysis
- Liquidity and slippage estimation
- Volatility tracking
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime
from typing import Any, Callable, Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics, OrderBook, Ticker
from app.utils.logging_config import Events, log_event
from app.utils.math_helpers import dynamic_slippage_from_orderbook

logger = logging.getLogger(__name__)


class MarketScanner:
    """
    Continuously scans configured markets and computes metrics.

    The scanner uses an adapter pattern — any exchange adapter implementing
    the BaseAdapter interface can be plugged in.
    """

    def __init__(
        self,
        adapter: Any,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._adapter = adapter
        self._settings = settings or get_settings()
        # Rolling price history per symbol for volatility calculation
        self._price_history: dict[str, deque[float]] = {
            symbol: deque(maxlen=100)
            for symbol in self._settings.symbols
        }
        # Cached latest metrics
        self._latest_metrics: dict[str, MarketMetrics] = {}
        # Registered callbacks for new metrics
        self._callbacks: list[Callable[[MarketMetrics], Any]] = []
        # Current polling interval (adaptive)
        self._current_interval: float = self._settings.polling_interval
        self._running: bool = False

    def register_callback(self, callback: Callable[[MarketMetrics], Any]) -> None:
        """Register a function to be called whenever new metrics are computed."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start the continuous market scanning loop."""
        self._running = True
        logger.info("MarketScanner started — symbols=%s", self._settings.symbols)
        while self._running:
            try:
                await self._scan_all_symbols()
            except Exception as e:
                log_event(logger, Events.FEED_ERROR, level="ERROR", error=str(e))
            await asyncio.sleep(self._current_interval)

    def stop(self) -> None:
        """Signal the scanner loop to stop."""
        self._running = False
        logger.info("MarketScanner stopping.")

    async def _scan_all_symbols(self) -> None:
        """Scan all configured symbols and update metrics."""
        max_volatility = 0.0
        for symbol in self._settings.symbols:
            try:
                metrics = await self._scan_symbol(symbol)
                self._latest_metrics[symbol] = metrics
                max_volatility = max(max_volatility, metrics.volatility)
                for cb in self._callbacks:
                    try:
                        cb(metrics)
                    except Exception as e:
                        logger.warning("Callback error for %s: %s", symbol, e)
            except Exception as e:
                log_event(logger, Events.FEED_ERROR, level="WARNING", symbol=symbol, error=str(e))

        # Adaptive polling: adjust interval based on observed volatility
        self._adjust_polling_interval(max_volatility)

    async def _scan_symbol(self, symbol: str) -> MarketMetrics:
        """
        Fetch order book + ticker, compute and return MarketMetrics.

        L2 slippage estimation uses actual order book depth — much more
        accurate than a static slippage buffer.
        """
        order_book: OrderBook = await self._adapter.fetch_order_book(symbol)
        ticker: Ticker = await self._adapter.fetch_ticker(symbol)

        # Track price history for volatility estimation
        if ticker.last > 0:
            self._price_history[symbol].append(ticker.last)

        volatility = self._estimate_volatility(symbol)

        # Estimate slippage from L2 data for a reference trade size
        ref_qty = 1.0  # Normalised reference quantity
        slippage_buy = dynamic_slippage_from_orderbook(
            ref_qty,
            order_book.as_ask_tuples(),
            side="buy",
        )
        slippage_sell = dynamic_slippage_from_orderbook(
            ref_qty,
            order_book.as_bid_tuples(),
            side="sell",
            bids=order_book.as_bid_tuples(),
        )

        # Effective spread includes taker fee (round-trip cost baseline)
        effective_spread = (order_book.spread_pct or 0.0) + 2 * self._settings.taker_fee

        metrics = MarketMetrics(
            symbol=symbol,
            exchange=order_book.exchange,
            timestamp=datetime.utcnow(),
            mid_price=order_book.mid_price or ticker.last,
            best_bid=order_book.best_bid or ticker.bid,
            best_ask=order_book.best_ask or ticker.ask,
            spread=order_book.spread or 0.0,
            spread_pct=order_book.spread_pct or 0.0,
            bid_depth=order_book.bid_depth(),
            ask_depth=order_book.ask_depth(),
            order_book_imbalance=order_book.imbalance(),
            estimated_slippage_buy=slippage_buy,
            estimated_slippage_sell=slippage_sell,
            volume_24h=ticker.volume_24h,
            volatility=volatility,
            effective_spread_with_taker=effective_spread,
        )

        return metrics

    def _estimate_volatility(self, symbol: str) -> float:
        """
        Estimate rolling volatility from price history.

        Uses log returns; annualised assuming 5-second intervals.
        Returns 0.0 if insufficient data.
        """
        import math
        prices = list(self._price_history[symbol])
        if len(prices) < 5:
            return 0.0

        log_returns = [
            math.log(prices[i] / prices[i - 1])
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]
        if not log_returns:
            return 0.0

        mean_return = sum(log_returns) / len(log_returns)
        variance = sum((r - mean_return) ** 2 for r in log_returns) / len(log_returns)
        std_per_interval = math.sqrt(variance)

        # Annualise: 5-second intervals → ~6,307,200 intervals/year
        intervals_per_year = 365 * 24 * 3600 / self._settings.polling_interval
        return std_per_interval * math.sqrt(intervals_per_year)

    def _adjust_polling_interval(self, current_volatility: float) -> None:
        """
        Adaptive polling: increase scan frequency in high-volatility periods.

        High vol → poll faster (more mispricing opportunities close quickly).
        Low vol  → poll slower (fewer opportunities, save API resources).
        """
        high_thresh = self._settings.high_volatility_threshold
        low_thresh = self._settings.low_volatility_threshold
        min_interval = self._settings.min_polling_interval
        max_interval = self._settings.max_polling_interval
        base = self._settings.polling_interval

        if current_volatility > high_thresh:
            new_interval = min_interval
        elif current_volatility < low_thresh:
            new_interval = max_interval
        else:
            # Linear interpolation between min and max
            frac = (current_volatility - low_thresh) / (high_thresh - low_thresh)
            new_interval = max_interval - frac * (max_interval - min_interval)

        if abs(new_interval - self._current_interval) > 0.5:
            logger.debug(
                "Adaptive polling: interval %.1fs → %.1fs (vol=%.2f)",
                self._current_interval, new_interval, current_volatility,
            )
            self._current_interval = new_interval

    def get_latest_metrics(self, symbol: str) -> Optional[MarketMetrics]:
        """Return the most recently computed metrics for a symbol."""
        return self._latest_metrics.get(symbol)

    def get_all_metrics(self) -> dict[str, MarketMetrics]:
        """Return metrics for all scanned symbols."""
        return dict(self._latest_metrics)
