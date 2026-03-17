# Trading Bot 🤖

A production-grade, modular Python trading bot that detects **mispricings**, **probability/price inconsistencies**, and **positive Expected Value (EV)** opportunities in the market.

> ⚠️ **This bot does NOT predict price direction.** It exploits measurable statistical edges.

---

## ⚠️ RISK WARNINGS — READ BEFORE USING

```
THIS SOFTWARE IS PROVIDED FOR EDUCATIONAL AND RESEARCH PURPOSES.

- NO PROFIT GUARANTEE: Past performance does not guarantee future results.
- RISK OF LOSS: You can lose all of your trading capital. Only use funds you can afford to lose entirely.
- EDGE DECAY: Any statistical edge can erode over time as markets become more efficient.
- EXECUTION RISK: Real-world slippage, latency, and fee changes can eliminate apparent edges.
- MODEL RISK: Edge estimates are based on limited historical data and may be overfit.
- REGULATORY RISK: Algorithmic trading may be subject to regulations in your jurisdiction.
- NO FINANCIAL ADVICE: Nothing in this codebase constitutes financial or investment advice.

THE AUTHORS ACCEPT NO RESPONSIBILITY FOR FINANCIAL LOSSES INCURRED USING THIS SOFTWARE.
```

---

## Philosophy

This bot is built on the following principles:

1. **EV-first**: Only trade when expected value (after fees, slippage, execution costs) is positive
2. **Risk-first**: Never risk more than the configured limits — hard rules, not suggestions
3. **Fractional Kelly**: Use 0.25 Kelly (quarter Kelly) by default — edge estimates are almost always overconfident
4. **Paper mode default**: All real order sending is OFF by default
5. **No leverage**: Leverage is disabled by default
6. **Transparency**: Every decision is logged with its reason

---

## Architecture

```
trading-bot/
├── app/
│   ├── main.py                    ← Entry point
│   ├── config.py                  ← Settings loader (YAML + .env)
│   ├── models/                    ← Pydantic data models
│   │   ├── market.py              ← OrderBook, Ticker, MarketMetrics
│   │   ├── signal.py              ← Trading signals
│   │   ├── trade.py               ← Orders and trades
│   │   ├── position.py            ← Open positions
│   │   └── risk.py                ← Risk events and state
│   ├── services/                  ← Core business logic
│   │   ├── market_scanner.py      ← Market data + adaptive polling
│   │   ├── ev_engine.py           ← EV calculation with decay + Bayesian
│   │   ├── position_sizer.py      ← Fractional Kelly sizing
│   │   ├── bankroll_manager.py    ← Capital management (tiered)
│   │   └── opportunity_scorer.py  ← Multi-factor opportunity scoring
│   ├── strategies/                ← Pluggable strategy implementations
│   │   ├── base_strategy.py       ← Abstract base class
│   │   ├── mispricing_strategy.py ← VWAP-based mispricing detection
│   │   ├── orderbook_imbalance_strategy.py ← Imbalance detection
│   │   └── cross_market_strategy.py ← Cross-venue arbitrage
│   ├── risk/                      ← Risk management layer
│   │   ├── risk_manager.py        ← Pre-trade risk checks
│   │   ├── kill_switch.py         ← Emergency halt
│   │   └── regime_detector.py     ← Volatility regime detection
│   ├── execution/                 ← Order execution
│   │   ├── base_adapter.py        ← Exchange adapter interface
│   │   ├── mock_adapter.py        ← Simulation adapter (default)
│   │   ├── live_adapter.py        ← Live adapter stub
│   │   ├── order_manager.py       ← Order lifecycle management
│   │   └── execution_engine.py    ← Trade orchestration + TWAP
│   ├── backtest/                  ← Backtesting infrastructure
│   │   ├── backtester.py          ← Historical replay engine
│   │   ├── simulator.py           ← Live paper trading simulator
│   │   └── reporter.py            ← Charts + CSV reports
│   ├── api/                       ← FastAPI dashboard
│   │   ├── app.py                 ← App factory
│   │   └── routes.py              ← API endpoints
│   ├── db/                        ← Database layer
│   │   ├── database.py            ← SQLite ORM models
│   │   └── repositories.py        ← Repository pattern DAOs
│   └── utils/
│       ├── logging_config.py      ← Structured logging setup
│       ├── math_helpers.py        ← Kelly, EV, Bayesian, statistics
│       └── alerting.py            ← Telegram/Discord webhooks
├── tests/                         ← Unit tests
├── data/                          ← Sample data + reports
├── templates/                     ← Dashboard HTML
├── logs/                          ← Log files
├── config.yaml                    ← All thresholds (edit this)
├── .env.example                   ← Environment template
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── Makefile
```

---

## Installation

### Prerequisites

- Python 3.12+
- pip

### Quick Start

```bash
# Clone the repository
git clone https://github.com/emre-eldemir/trading-bot.git
cd trading-bot

# Install dependencies
make install
# or: pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Run paper trading (safe — no real orders)
make paper-trade
# or: python -m app.main
```

### Docker

```bash
# Build image
make build

# Run with Docker (paper mode)
make run
# or: docker-compose up trading-bot
```

---

## Running Modes

### 1. Paper Trading (Default — Safe)

```bash
python -m app.main
# or
make paper-trade
```

All strategy logic runs in full. Orders are simulated via the mock adapter. No real exchange connection required.

### 2. Backtesting

```bash
python -m app.main --backtest
# or
make backtest
```

Replays historical data through the strategy pipeline. Results are saved to `data/reports/`.

### 3. API Dashboard

```bash
python -m app.main --api
# or
make api
```

Starts the FastAPI web dashboard at http://localhost:8000

---

## Configuration

All thresholds are in `config.yaml`. Secrets (API keys) go in `.env`.

Key settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `simulation_mode` | `true` | Paper trading mode |
| `live_trading` | `false` | Real order sending |
| `kelly_fraction` | `0.25` | Fractional Kelly multiplier |
| `min_edge` | `0.005` | Minimum 0.5% edge required |
| `min_ev` | `0.003` | Minimum EV after fees |
| `max_drawdown` | `0.15` | Kill switch triggers at 15% |
| `daily_max_loss` | `0.02` | Halt at 2% daily loss |
| `max_open_positions` | `5` | Maximum concurrent positions |
| `active_capital_ratio` | `0.50` | 50% of capital is tradeable |

---

## Checklist Before Going Live

⚠️ **Do NOT go live without completing every item on this list:**

- [ ] Ran paper trading for at least **2 weeks** minimum
- [ ] Reviewed all risk parameters in `config.yaml`
- [ ] Verified kill switch activates correctly in testing
- [ ] Confirmed daily loss limit and drawdown limit work
- [ ] Tested with very small real capital first
- [ ] Verified exchange API credentials are correct
- [ ] Reviewed all exchange fees (maker/taker) are configured correctly
- [ ] Checked your jurisdiction's regulatory requirements
- [ ] Set up Telegram/Discord alerts for critical events
- [ ] Reviewed the `live_adapter.py` implementation for your exchange
- [ ] Understood and accepted the risk warnings at the top of this README
- [ ] Never use funds you cannot afford to lose entirely

---

## Strategies

### 1. Mispricing Detection
Computes rolling VWAP fair value from recent price history. Generates signals when the current best bid/ask deviates from fair value by more than `min_edge` + fees.

### 2. Order Book Imbalance
Detects strong bid/ask imbalances. When one side dominates significantly (>30%), it suggests imminent price pressure in that direction.

### 3. Cross-Market Arbitrage
Compares prices of the same asset across different venues. Signals when the spread between venues exceeds fees + minimum profit threshold.

---

## EV Calculation Pipeline

Every signal goes through this pipeline before execution:

```
Raw Signal
    ↓
Signal Decay (age-based EV reduction)
    ↓
Bayesian Edge Adjustment (confidence-weighted)
    ↓
Edge Threshold Check (min_edge)
    ↓
EV = win_prob * win_amount - loss_prob * loss_amount
    ↓
Fee Deduction (maker + taker, round-trip)
    ↓
Dynamic Slippage (from L2 order book depth)
    ↓
Execution Delay Cost
    ↓
Min EV Threshold Check
    ↓
Opportunity Scoring
    ↓
Risk Pre-Trade Check
    ↓
Execute or Reject
```

---

## Development Roadmap

### Phase 1 — MVP (Current)
- [x] Core EV engine with fees/slippage
- [x] Fractional Kelly position sizing
- [x] Signal decay function
- [x] Bayesian edge estimation
- [x] Mispricing + orderbook + cross-market strategies
- [x] Risk management (kill switch, drawdown, daily loss)
- [x] Paper trading simulator
- [x] Backtesting engine
- [x] FastAPI dashboard
- [x] Mock adapter (no API keys needed)

### Phase 2 — Exchange Integration
- [ ] Implement LiveAdapter for Binance/Bybit/Kraken
- [ ] Real order book data ingestion
- [ ] WebSocket streaming support
- [ ] CCXT integration for multi-exchange

### Phase 3 — Enhanced Analytics
- [ ] ML-based opportunity scoring (XGBoost/LightGBM)
- [ ] More sophisticated correlation matrix
- [ ] Portfolio optimization (mean-variance)
- [ ] Multi-timeframe analysis

### Phase 4 — Production Hardening
- [ ] Redis-based caching for market data
- [ ] PostgreSQL migration from SQLite
- [ ] Kubernetes deployment manifests
- [ ] Grafana/Prometheus monitoring integration
- [ ] Automated strategy health monitoring

---

## Mathematical Documentation

See `MATH_DOCS.md` for detailed mathematical explanations of:
- Kelly Criterion derivation
- EV calculation with fee adjustments
- Bayesian edge estimation
- Signal decay function
- Correlation-adjusted position sizing
- Sharpe ratio and drawdown metrics

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run tests: `make test`
4. Run linter: `make lint`
5. Submit a pull request

---

## License

MIT License — see LICENSE file.

**Remember: This is for educational purposes. No profit is guaranteed. Trade responsibly.**