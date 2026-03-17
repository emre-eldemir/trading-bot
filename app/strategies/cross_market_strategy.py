"""
app/strategies/cross_market_strategy.py — Cross-market price inconsistency detection.

Logic:
- Compare prices of the same asset on two different venues
- Detect when one venue prices significantly higher/lower than the other
- Signal: BUY on cheaper venue, SELL on more expensive venue (arbitrage)
- Accounts for fees on both venues and transfer time/cost
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import TradingConfig, get_settings
from app.models.market import MarketMetrics
from app.models.signal import Signal, SignalDirection, SignalType
from app.strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class CrossMarketStrategy(BaseStrategy):
    """
    Detects cross-venue price inconsistencies (statistical arbitrage).

    Requires metrics from at least two exchanges for the same symbol.
    Context dict must contain: {'exchanges': {exchange_name: MarketMetrics}}
    """

    def __init__(
        self,
        min_arb_spread: float = 0.002,  # Minimum 0.2% spread to act
        settings: Optional[TradingConfig] = None,
    ) -> None:
        super().__init__(name="cross_market", settings=settings)
        self._min_arb_spread = min_arb_spread

    def name_str(self) -> str:
        return "Cross-Market Arbitrage Strategy"

    def generate_signals(
        self,
        metrics: MarketMetrics,
        context: Optional[dict] = None,
    ) -> list[Signal]:
        """
        Detect cross-venue arbitrage opportunities.

        Args:
            metrics: Metrics for the primary venue.
            context: Must include 'exchanges' dict with other venue metrics.

        Returns:
            List of arbitrage signals.
        """
        if not self._enabled:
            return []

        if context is None or "exchanges" not in context:
            return []

        other_exchanges: dict[str, MarketMetrics] = context["exchanges"]
        if not other_exchanges:
            return []

        signals: list[Signal] = []
        primary = metrics

        for other_exchange, other_metrics in other_exchanges.items():
            if other_exchange == primary.exchange:
                continue
            if other_metrics.symbol != primary.symbol:
                continue

            arb_signals = self._check_arb(primary, other_metrics)
            signals.extend(arb_signals)

        return signals

    def _check_arb(
        self,
        venue_a: MarketMetrics,
        venue_b: MarketMetrics,
    ) -> list[Signal]:
        """
        Check for arbitrage between two venues.

        Arb opportunity: buy on A (ask_A), sell on B (bid_B)
        Net spread = bid_B - ask_A (must exceed fees + min_arb_spread)
        """
        signals: list[Signal] = []

        if venue_a.best_ask <= 0 or venue_b.best_bid <= 0:
            return signals

        # Direction 1: Buy on A, sell on B
        spread_ab = (venue_b.best_bid - venue_a.best_ask) / venue_a.best_ask
        total_fees = (self._settings.taker_fee * 2)  # Fee on both legs
        net_spread_ab = spread_ab - total_fees - self._min_arb_spread

        if net_spread_ab > self._settings.min_edge:
            win_prob = min(0.80, 0.60 + net_spread_ab * 10)  # Higher spread = more confidence
            signals.append(self._build_arb_signal(
                primary=venue_a,
                secondary=venue_b,
                direction=SignalDirection.BUY,
                entry_price=venue_a.best_ask,
                fair_value=venue_b.best_bid,
                edge=net_spread_ab,
                win_prob=win_prob,
            ))

        # Direction 2: Buy on B, sell on A
        if venue_b.best_ask > 0 and venue_a.best_bid > 0:
            spread_ba = (venue_a.best_bid - venue_b.best_ask) / venue_b.best_ask
            net_spread_ba = spread_ba - total_fees - self._min_arb_spread

            if net_spread_ba > self._settings.min_edge:
                win_prob = min(0.80, 0.60 + net_spread_ba * 10)
                signals.append(self._build_arb_signal(
                    primary=venue_b,
                    secondary=venue_a,
                    direction=SignalDirection.BUY,
                    entry_price=venue_b.best_ask,
                    fair_value=venue_a.best_bid,
                    edge=net_spread_ba,
                    win_prob=win_prob,
                ))

        return signals

    def _build_arb_signal(
        self,
        primary: MarketMetrics,
        secondary: MarketMetrics,
        direction: SignalDirection,
        entry_price: float,
        fair_value: float,
        edge: float,
        win_prob: float,
    ) -> Signal:
        return Signal(
            strategy=self.name,
            signal_type=SignalType.CROSS_MARKET,
            symbol=primary.symbol,
            exchange=primary.exchange,
            direction=direction,
            entry_price=entry_price,
            fair_value=fair_value,
            raw_edge=edge,
            win_probability=win_prob,
            confidence=win_prob * 0.90,
            num_observations=5,  # Cross-market signals have inherent confidence
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=15),  # Arb closes very fast
            notes=f"arb: {primary.exchange} vs {secondary.exchange}",
        )
