# Mathematical Documentation — Trading Bot

This document explains the mathematical foundations of the trading bot's key algorithms.

---

## 1. Kelly Criterion

### Full Kelly

The Kelly Criterion finds the fraction `f*` of capital to bet that maximises long-run logarithmic growth:

```
f* = (b·p - q) / b

where:
  p = probability of winning
  q = 1 - p (probability of losing)
  b = net odds (win_payout / loss_payout)
```

**Example:** If p=0.60, b=1.0 (even money):
```
f* = (1.0 × 0.60 - 0.40) / 1.0 = 0.20 → bet 20% of bankroll
```

**Important:** Kelly requires accurate win probability estimates. In practice, estimates are almost always overconfident.

### Fractional Kelly (Default: 0.25)

To account for edge overestimation and reduce variance:

```
f_frac = f* × fraction

where fraction ∈ (0, 1], default = 0.25
```

**Why 0.25?**
- Full Kelly with overestimated edges leads to ruin
- Quarter Kelly gives ~81% of full Kelly's long-run growth rate
- Much lower drawdown and variance
- More robust to edge estimation errors

### Dynamic Kelly Fraction

As drawdown increases, we reduce the fraction to protect capital:

```
f_dynamic = f_frac × multiplier(drawdown)

where multiplier is configured as:
  drawdown ≥ 5%  → multiplier = 0.75
  drawdown ≥ 10% → multiplier = 0.50
  drawdown ≥ 20% → multiplier = 0.25
```

This implements a form of "bet down as you lose" protection.

---

## 2. Expected Value (EV)

### Basic EV

```
EV = p · W - (1-p) · L

where:
  p = win probability
  W = win amount (in dollars)
  L = loss amount (in dollars)
```

**Only trade when EV > 0 after all costs.**

### EV After Fees

Round-trip fee cost for a position of size S:

```
fee_cost = 2 × S × fee_rate

EV_net_fees = EV_raw - fee_cost
```

We prefer **maker fees** (limit orders) over **taker fees** (market orders):
- Maker: 0.02% (placing limit orders that add liquidity)
- Taker: 0.05% (market orders that take liquidity)

### EV After Slippage

Dynamic slippage from order book depth:

```
avg_fill_price = Σ(price_i × fill_i) / Σ fill_i
                 for levels consumed to fill quantity

slippage = |avg_fill_price - best_price| / best_price

EV_net_slippage = EV_net_fees - slippage × S
```

This is significantly more accurate than a static slippage buffer.

### EV After Execution Delay

Approximation of cost from market moving during execution delay:

```
delay_cost = σ × √(delay / T) × S × 0.5

where:
  σ = annualised volatility
  delay = execution delay in seconds
  T = seconds per year
```

### Final Net EV

```
EV_final = EV_raw - fee_cost - slippage_cost - delay_cost
```

**Trade is executed only if EV_final ≥ min_ev threshold.**

---

## 3. Signal Decay Function

Mispricing opportunities close over time as other market participants respond. We model this as exponential decay:

```
decay_factor = 2^(-age / half_life)

where:
  age = time since signal was created (seconds)
  half_life = configured half-life (default: 60 seconds)
```

**Examples:**
- age = 0:          decay = 1.0 (full EV)
- age = half_life:  decay = 0.5 (half EV)
- age = 2×half_life: decay = 0.25 (quarter EV)

Applied to EV:
```
EV_decayed = EV_raw × decay_factor
```

**Why exponential?** Arbitrage opportunities don't decay linearly. The initial response is fast as algorithms react, then slows as obvious participants exit.

---

## 4. Bayesian Edge Estimation

Raw edge estimates from small samples are unreliable. We apply Bayesian shrinkage toward zero (skeptical prior):

```
posterior_edge = (prior_mean × prior_strength + observed_edge × n) / (prior_strength + n)

confidence = n / (n + prior_strength)

where:
  prior_mean = 0 (skeptical: assume no edge)
  prior_strength = 10 (equivalent to 10 observations saying "no edge")
  n = number of observations
```

**Effect:**
- With 1 observation: heavy shrinkage toward 0
- With 10 observations: 50/50 between observed and prior
- With 100+ observations: mostly observed edge

This prevents us from acting on 1-2 lucky observations as if they represent a real edge.

The position size is then scaled by confidence:

```
adjusted_edge = posterior_edge × confidence
```

---

## 5. Correlation-Adjusted Kelly

When multiple correlated positions are open, we reduce new position size:

```
correlated_exposure = Σ size_i  (for all positions with |corr_i| ≥ threshold)

reduction = 1 / (1 + correlated_exposure)

adjusted_size = kelly_size × reduction
```

**Why?** Two highly correlated positions are essentially the same bet. Adding them compounds risk without proportionally increasing expected return.

---

## 6. Order Book Imbalance

```
imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)

Range: [-1, +1]
  +1 = only bids (strong buy pressure)
  -1 = only asks (strong sell pressure)
   0 = perfectly balanced
```

Signal threshold: |imbalance| > 0.30 (configurable)

Win probability from imbalance:
```
win_prob ≈ 0.50 + 0.25 × |imbalance|

Capped at 0.75 to prevent overconfidence.
```

---

## 7. Dynamic Slippage from L2 Order Book

Walking the order book to estimate fill price:

```
for each level (price_i, size_i) until quantity is filled:
    fill = min(remaining_quantity, size_i)
    weighted_price += price_i × fill
    total_filled += fill
    remaining -= fill

avg_price = weighted_price / total_filled
slippage = |avg_price - best_price| / best_price
```

This gives a realistic, quantity-dependent slippage estimate rather than a fixed percentage.

---

## 8. Adaptive Polling Interval

To optimise API usage:

```
if volatility > high_threshold:
    interval = min_interval  (fast polling)
elif volatility < low_threshold:
    interval = max_interval  (slow polling)
else:
    # Linear interpolation
    frac = (volatility - low_threshold) / (high_threshold - low_threshold)
    interval = max_interval - frac × (max_interval - min_interval)
```

**Why?** Mispricing opportunities arise and close faster in high-volatility markets. Slow polling wastes API calls when markets are quiet.

---

## 9. Opportunity Score

Multi-factor composite score:

```
score = w_ev × score_ev
      + w_liq × score_liquidity
      + w_conf × score_confidence
      + w_fresh × score_freshness

where default weights: w_ev=0.40, w_liq=0.25, w_conf=0.20, w_fresh=0.15

score_ev = tanh(2 × relative_ev / 0.01)  [scaled sigmoid]
score_liquidity = 0.5 × spread_score + 0.5 × depth_score
score_confidence = confidence  [Bayesian weight]
score_freshness = decay_factor(age)
```

Only opportunities with score ≥ min_score (default: 0.50) are executed.

---

## 10. Performance Metrics

### Sharpe Ratio (annualised)

```
Sharpe = (mean_return - rf_rate/N) / std_return × √N

where N = periods per year
```

A Sharpe > 1.0 is generally considered good. Note: our trades are not i.i.d., so Sharpe has limitations.

### Maximum Drawdown

```
max_dd = max over all times t of: (peak_before_t - trough_after_peak) / peak_before_t
```

Measures the worst peak-to-trough decline in equity.

### Expectancy

```
expectancy = Σ pnl_i / n_trades = mean PnL per trade
```

Positive expectancy is necessary (but not sufficient) for long-run profitability.

---

## References

- Kelly, J.L. (1956). "A New Interpretation of Information Rate." Bell System Technical Journal.
- Thorp, E.O. (2006). "The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market."
- MacLean, L.C., Thorp, E.O., Ziemba, W.T. (2011). "The Kelly Capital Growth Investment Criterion."
