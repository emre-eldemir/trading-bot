"""
app/execution/execution_engine.py — Trade execution orchestrator.

Coordinates signal → position sizing → risk check → order submission.

Features:
- TWAP execution for large orders (split into slices)
- Stale signal detection before execution
- Paper trading mode (no real orders sent)
- Full lifecycle: open → monitor → close
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.config import TradingConfig, get_settings
from app.execution.order_manager import OrderManager
from app.models.position import Position, PositionSide
from app.models.signal import Signal, SignalDirection
from app.models.trade import Order, OrderSide, OrderStatus, OrderType, Trade
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskManager
from app.services.bankroll_manager import BankrollManager
from app.services.position_sizer import PositionSizer
from app.utils.logging_config import Events, log_event

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Orchestrates the full trade execution lifecycle.

    Flow:
    1. Receive evaluated signal (positive EV)
    2. Compute position size
    3. Run risk checks
    4. Submit order (or skip in paper mode)
    5. Track open position
    6. Close position on exit signal / stop
    """

    def __init__(
        self,
        order_manager: OrderManager,
        position_sizer: PositionSizer,
        bankroll: BankrollManager,
        risk_manager: RiskManager,
        kill_switch: KillSwitch,
        settings: Optional[TradingConfig] = None,
    ) -> None:
        self._order_mgr = order_manager
        self._sizer = position_sizer
        self._bankroll = bankroll
        self._risk = risk_manager
        self._kill_switch = kill_switch
        self._settings = settings or get_settings()
        self._open_positions: dict[str, Position] = {}  # position_id → Position
        self._closed_trades: list[Trade] = []

    async def execute_signal(self, signal: Signal) -> Optional[Position]:
        """
        Attempt to execute a signal as a trade.

        Returns the opened Position, or None if execution was rejected/skipped.
        """
        # Guard: kill switch
        if self._kill_switch.is_active:
            logger.warning("Execution blocked: kill switch active")
            return None

        # Stale signal check
        if signal.is_expired:
            log_event(logger, Events.TRADE_REJECTED, reason="signal_expired", signal_id=signal.id)
            return None

        # Compute dollar size
        open_positions_list = list(self._open_positions.values())
        open_sizes = [p.notional_value / self._bankroll.total_equity for p in open_positions_list]
        dollar_size = self._sizer.compute_dollar_size(signal, open_sizes)

        if dollar_size <= 0:
            log_event(logger, Events.TRADE_REJECTED, reason="zero_size", signal_id=signal.id)
            return None

        # Apply regime risk multiplier
        dollar_size *= self._risk._regime.risk_multiplier

        # Risk pre-trade check
        allowed, reason = self._risk.check_pre_trade(signal, dollar_size, open_positions_list)
        if not allowed:
            log_event(logger, Events.TRADE_REJECTED, reason=reason, signal_id=signal.id)
            return None

        # Determine quantity from dollar size and entry price
        quantity = dollar_size / signal.entry_price if signal.entry_price > 0 else 0
        if quantity <= 0:
            return None

        # Paper trading: simulate without sending real orders
        if self._settings.simulation_mode:
            return await self._paper_trade(signal, quantity, dollar_size)

        # Live: submit real order
        return await self._live_trade(signal, quantity, dollar_size)

    async def _paper_trade(
        self,
        signal: Signal,
        quantity: float,
        dollar_size: float,
    ) -> Position:
        """Simulate a trade without real order submission."""
        order_side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        order = Order(
            symbol=signal.symbol,
            exchange=signal.exchange,
            side=order_side,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=signal.entry_price,
            signal_id=signal.id,
        )

        # Use mock adapter for paper fills
        filled = await self._order_mgr.submit(order)
        if filled.status != OrderStatus.FILLED:
            await asyncio.sleep(0.1)  # Brief wait for paper fill
            filled = await self._order_mgr.wait_for_fill(filled)

        if filled.status != OrderStatus.FILLED:
            log_event(logger, Events.TRADE_REJECTED, reason="paper_fill_failed", signal_id=signal.id)
            return None

        # Register the position
        position = self._create_position(signal, filled)
        self._open_positions[position.id] = position
        self._bankroll.allocate(dollar_size)

        log_event(
            logger, Events.TRADE_OPENED,
            position_id=position.id,
            symbol=signal.symbol,
            direction=signal.direction.value,
            qty=quantity,
            price=filled.average_fill_price,
            dollar_size=dollar_size,
            mode="paper",
        )
        return position

    async def _live_trade(
        self,
        signal: Signal,
        quantity: float,
        dollar_size: float,
    ) -> Optional[Position]:
        """Submit a real order to the exchange."""
        if not self._settings.live_trading:
            logger.error("Live trade blocked: live_trading=False")
            return None

        order_side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL

        # Use TWAP for large orders to reduce market impact
        if dollar_size / self._bankroll.total_equity > self._settings.large_order_threshold:
            return await self._twap_execute(signal, quantity, dollar_size, order_side)

        order = Order(
            symbol=signal.symbol,
            exchange=signal.exchange,
            side=order_side,
            order_type=OrderType.LIMIT if self._settings.prefer_maker else OrderType.MARKET,
            quantity=quantity,
            price=signal.entry_price,
            signal_id=signal.id,
        )

        filled = await self._order_mgr.submit(order)
        filled = await self._order_mgr.wait_for_fill(filled)

        if filled.status != OrderStatus.FILLED:
            return None

        position = self._create_position(signal, filled)
        self._open_positions[position.id] = position
        self._bankroll.allocate(dollar_size)

        log_event(
            logger, Events.TRADE_OPENED,
            position_id=position.id,
            symbol=signal.symbol,
            direction=signal.direction.value,
            mode="live",
        )
        return position

    async def _twap_execute(
        self,
        signal: Signal,
        total_quantity: float,
        dollar_size: float,
        side: OrderSide,
    ) -> Optional[Position]:
        """
        TWAP execution: split large order into N equal slices over time.
        Reduces market impact for larger positions.
        """
        slices = self._settings.twap_slices
        slice_qty = total_quantity / slices
        interval = self._settings.twap_interval

        logger.info(
            "TWAP execution: %d slices of %.4f %s every %.0fs",
            slices, slice_qty, signal.symbol, interval,
        )

        total_filled = 0.0
        total_cost = 0.0
        last_order = None

        for i in range(slices):
            order = Order(
                symbol=signal.symbol,
                exchange=signal.exchange,
                side=side,
                order_type=OrderType.LIMIT,
                quantity=slice_qty,
                price=signal.entry_price,
                signal_id=f"{signal.id}_slice_{i}",
            )
            filled = await self._order_mgr.submit(order)
            filled = await self._order_mgr.wait_for_fill(filled)
            if filled.status == OrderStatus.FILLED:
                total_filled += filled.filled_quantity
                total_cost += filled.filled_quantity * (filled.average_fill_price or 0)
                last_order = filled

            if i < slices - 1:
                await asyncio.sleep(interval)

        if last_order and total_filled > 0:
            avg_price = total_cost / total_filled
            last_order = last_order.model_copy(update={
                "filled_quantity": total_filled,
                "average_fill_price": avg_price,
            })
            signal = signal.model_copy(update={"entry_price": avg_price})
            position = self._create_position(signal, last_order)
            self._open_positions[position.id] = position
            self._bankroll.allocate(dollar_size)
            return position

        return None

    async def close_position(
        self,
        position: Position,
        exit_price: float,
    ) -> Optional[Trade]:
        """Close an open position and record the trade."""
        if position.id not in self._open_positions:
            logger.warning("Position %s not found in open positions", position.id)
            return None

        # Simulate exit
        side = OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
        order = Order(
            symbol=position.symbol,
            exchange=position.exchange,
            side=side,
            order_type=OrderType.MARKET,
            quantity=position.quantity,
            price=exit_price,
        )

        if not self._settings.simulation_mode and self._settings.live_trading:
            filled = await self._order_mgr.submit(order)
            filled = await self._order_mgr.wait_for_fill(filled)
            actual_exit = filled.average_fill_price or exit_price
        else:
            actual_exit = exit_price  # Paper: use provided exit price

        # Compute PnL
        entry_value = position.entry_price * position.quantity
        exit_value = actual_exit * position.quantity
        if position.side == PositionSide.LONG:
            gross_pnl = exit_value - entry_value
        else:
            gross_pnl = entry_value - exit_value

        fees = (entry_value + exit_value) * self._settings.taker_fee
        net_pnl = gross_pnl - fees

        # Build trade record
        trade = Trade(
            symbol=position.symbol,
            exchange=position.exchange,
            direction=position.side.value,
            entry_order_id=position.entry_order_id,
            entry_price=position.entry_price,
            exit_price=actual_exit,
            quantity=position.quantity,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            strategy=position.strategy,
            signal_id=position.signal_id,
            opened_at=position.opened_at,
            closed_at=datetime.now(timezone.utc),
            hold_duration_seconds=(datetime.now(timezone.utc) - position.opened_at).total_seconds(),
        )

        # Update bankroll
        self._bankroll.release(
            amount=position.notional_value,
            pnl=net_pnl,
        )
        self._risk.update_on_close(net_pnl)

        # Remove from open positions
        del self._open_positions[position.id]
        self._closed_trades.append(trade)

        log_event(
            logger, Events.TRADE_CLOSED,
            trade_id=trade.id,
            symbol=trade.symbol,
            net_pnl=f"{net_pnl:.4f}",
            gross_pnl=f"{gross_pnl:.4f}",
            fees=f"{fees:.4f}",
        )
        return trade

    def _create_position(self, signal: Signal, order: Order) -> Position:
        """Build a Position from a filled order and signal."""
        side = PositionSide.LONG if signal.direction == SignalDirection.BUY else PositionSide.SHORT
        return Position(
            symbol=signal.symbol,
            exchange=signal.exchange,
            side=side,
            quantity=order.filled_quantity,
            entry_price=order.average_fill_price or signal.entry_price,
            current_price=order.average_fill_price or signal.entry_price,
            entry_order_id=order.id,
            signal_id=signal.id,
            strategy=signal.strategy,
            target_price=signal.target_price,
            stop_price=signal.stop_price,
        )

    @property
    def open_positions(self) -> list[Position]:
        return list(self._open_positions.values())

    @property
    def closed_trades(self) -> list[Trade]:
        return list(self._closed_trades)

    def update_position_prices(self, symbol: str, current_price: float) -> None:
        """Update current price for all positions in the given symbol."""
        for pos in self._open_positions.values():
            if pos.symbol == symbol:
                self._open_positions[pos.id] = pos.model_copy(update={
                    "current_price": current_price,
                    "updated_at": datetime.now(timezone.utc),
                })
