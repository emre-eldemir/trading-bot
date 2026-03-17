"""
app/utils/math_helpers.py — Mathematical utility functions.

Contains Kelly Criterion, EV calculations, signal decay, Bayesian
confidence, correlation calculations, and other quant helpers.

All formulas are documented in MATH_DOCS.md.
"""

from __future__ import annotations

import math
from typing import Sequence


# ---------------------------------------------------------------------------
# Kelly Criterion
# ---------------------------------------------------------------------------

def kelly_fraction(
    win_probability: float,
    win_payout: float,
    loss_payout: float = 1.0,
) -> float:
    """
    Classic Kelly Criterion formula: f* = (bp - q) / b
    where b = win_payout/loss_payout, p = win_prob, q = 1 - p.

    Args:
        win_probability: Probability of winning (0 < p < 1).
        win_payout: Net payout ratio on a win (e.g., 1.0 = 100% profit).
        loss_payout: Net loss ratio on a loss (e.g., 1.0 = 100% loss).

    Returns:
        Optimal Kelly fraction. Negative means no edge — don't bet.
    """
    if win_probability <= 0 or win_probability >= 1:
        return 0.0
    b = win_payout / loss_payout
    q = 1.0 - win_probability
    return (b * win_probability - q) / b


def fractional_kelly(
    win_probability: float,
    win_payout: float,
    fraction: float = 0.25,
    loss_payout: float = 1.0,
) -> float:
    """
    Fractional Kelly: multiply full Kelly by a conservative fraction.

    Why 0.25? Real-world edge estimates are often overconfident.
    Fractional Kelly reduces ruin risk dramatically with modest EV cost.

    Returns:
        Fractional Kelly bet size (0 if no edge).
    """
    full = kelly_fraction(win_probability, win_payout, loss_payout)
    return max(0.0, full * fraction)


def dynamic_kelly_fraction(
    base_fraction: float,
    current_drawdown: float,
    thresholds: list[dict],
) -> float:
    """
    Reduce Kelly fraction as drawdown increases.

    Thresholds example:
        [{"drawdown": 0.05, "multiplier": 0.75},
         {"drawdown": 0.10, "multiplier": 0.50}]

    The largest applicable threshold multiplier is applied.
    """
    multiplier = 1.0
    for entry in sorted(thresholds, key=lambda x: x["drawdown"], reverse=True):
        if current_drawdown >= entry["drawdown"]:
            multiplier = entry["multiplier"]
            break
    return base_fraction * multiplier


def correlation_adjusted_kelly(
    kelly_size: float,
    open_positions: list[float],
    correlations: list[float],
    correlation_threshold: float = 0.70,
) -> float:
    """
    Reduce position size when correlated positions already exist.

    For each existing position with correlation > threshold, we scale down
    the new position proportionally to avoid excessive correlated exposure.

    Args:
        kelly_size: Raw Kelly position size.
        open_positions: List of existing position sizes (as fractions of bankroll).
        correlations: Correlation of each existing position with new trade.
        correlation_threshold: Correlation above which we reduce sizing.

    Returns:
        Adjusted position size.
    """
    if not open_positions:
        return kelly_size

    correlated_exposure = sum(
        size for size, corr in zip(open_positions, correlations)
        if abs(corr) >= correlation_threshold
    )

    # Reduce new position proportionally to correlated exposure already in portfolio
    reduction = 1.0 / (1.0 + correlated_exposure)
    return kelly_size * reduction


# ---------------------------------------------------------------------------
# Expected Value
# ---------------------------------------------------------------------------

def expected_value(
    win_probability: float,
    win_amount: float,
    loss_amount: float,
) -> float:
    """
    Basic Expected Value: EV = p * win - (1-p) * loss.

    All amounts should be in the same units (e.g., dollars or fractions).
    """
    return win_probability * win_amount - (1.0 - win_probability) * loss_amount


def ev_after_fees(
    raw_ev: float,
    position_size: float,
    maker_fee: float = 0.0002,
    taker_fee: float = 0.0005,
    use_maker: bool = True,
) -> float:
    """
    Adjust EV for trading fees (both entry and exit).

    fee_cost = 2 * position_size * fee_rate  (round-trip cost)
    """
    fee_rate = maker_fee if use_maker else taker_fee
    fee_cost = 2.0 * position_size * fee_rate
    return raw_ev - fee_cost


def ev_after_slippage(
    ev: float,
    slippage: float,
    position_size: float,
) -> float:
    """
    Adjust EV for estimated slippage cost.

    slippage is expressed as a fraction of the trade value.
    """
    slippage_cost = slippage * position_size
    return ev - slippage_cost


def dynamic_slippage_from_orderbook(
    quantity: float,
    asks: list[tuple[float, float]],  # (price, size) levels
    side: str = "buy",
    bids: list[tuple[float, float]] | None = None,
) -> float:
    """
    Estimate slippage by walking the order book for a given quantity.

    Returns slippage as a fraction of the mid price.
    Unlike a fixed buffer, this reflects actual market depth.
    """
    levels = asks if side == "buy" else (bids or [])
    if not levels:
        return 0.001  # Fallback to 0.1%

    remaining = quantity
    weighted_price = 0.0
    total_filled = 0.0

    for price, size in levels:
        fill = min(remaining, size)
        weighted_price += price * fill
        total_filled += fill
        remaining -= fill
        if remaining <= 0:
            break

    if total_filled == 0:
        return 0.001

    avg_price = weighted_price / total_filled
    best_price = levels[0][0]
    if best_price == 0:
        return 0.001

    return abs(avg_price - best_price) / best_price


# ---------------------------------------------------------------------------
# Signal Decay
# ---------------------------------------------------------------------------

def signal_decay_factor(age_seconds: float, half_life: float = 60.0) -> float:
    """
    Exponential decay factor for signal freshness.

    EV_adjusted = EV_raw * decay_factor
    decay_factor = 2^(-age / half_life)

    At age=0: factor=1.0 (full EV)
    At age=half_life: factor=0.5 (half EV)
    At age=2*half_life: factor=0.25 (quarter EV)

    Why? Mispricing opportunities close over time as arbitrageurs act.
    """
    if half_life <= 0:
        return 1.0
    return math.pow(2.0, -age_seconds / half_life)


# ---------------------------------------------------------------------------
# Bayesian Edge Estimation
# ---------------------------------------------------------------------------

def bayesian_edge_confidence(
    observed_edge: float,
    num_observations: int,
    prior_mean: float = 0.0,
    prior_strength: float = 10,
) -> tuple[float, float]:
    """
    Bayesian update: combine observed edge with a skeptical prior.

    Uses a simple Bayesian mean shrinkage toward zero (skeptical prior).
    The more observations, the more we trust the observed edge.

    Returns:
        (posterior_edge, confidence_weight)
        confidence_weight in [0, 1] — use to scale position size.
    """
    # Posterior mean = weighted average of prior and observed
    total_weight = prior_strength + num_observations
    posterior_edge = (prior_mean * prior_strength + observed_edge * num_observations) / total_weight

    # Confidence grows with observations — logistic scaling
    confidence = num_observations / (num_observations + prior_strength)
    return posterior_edge, confidence


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def sharpe_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Annualised Sharpe ratio from a sequence of period returns."""
    if len(returns) < 2:
        return 0.0
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    if std_dev == 0:
        return 0.0
    excess = mean_return - risk_free_rate / periods_per_year
    return (excess / std_dev) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: Sequence[float]) -> float:
    """
    Maximum peak-to-trough drawdown from an equity curve.
    Returns a positive fraction (e.g., 0.15 = 15% drawdown).
    """
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


def win_rate(pnls: Sequence[float]) -> float:
    """Fraction of trades with positive PnL."""
    if not pnls:
        return 0.0
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)


def expectancy(pnls: Sequence[float]) -> float:
    """Average PnL per trade (expectancy)."""
    if not pnls:
        return 0.0
    return sum(pnls) / len(pnls)


def spread_percentage(bid: float, ask: float) -> float:
    """Bid-ask spread as a percentage of mid price."""
    if bid <= 0 or ask <= 0:
        return 0.0
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid if mid > 0 else 0.0


def implied_probability(price: float, total_market: float = 1.0) -> float:
    """
    Convert a price to an implied probability.

    For binary markets: prob = price / 1.0
    For normalised markets: prob = price / total_market
    """
    if total_market <= 0:
        return 0.0
    return max(0.0, min(1.0, price / total_market))
