# ORB Backtest Report — EUR/USD + GBP/USD (M15)

**Date:** 2026-07-03  
**Analyst:** Tsukasa (autonomous build)  
**Config files:** `config/backtest/orb_eurusd.yaml`, `config/backtest/orb_gbpusd.yaml`  
**Data source:** `data/forex/historical/EURUSD_M15.csv`, `data/forex/historical/GBPUSD_M15.csv`  
**Backtest period:** 2025-01-01 to 2026-04-10 (M15 bars only)  

---

## 1. Strategy Description

**Opening Range Breakout (ORB)** on London and NY sessions:

- **London range:** 07:00–08:00 UTC (60 min). Trade 08:00–16:00 UTC.
- **NY range:** 12:00–12:30 UTC (30 min). Trade 12:30–21:00 UTC.
- **Entry:** Breakout beyond OR high/low by threshold pips (2.0 EURUSD, 2.5 GBPUSD).
- **Stop loss:** ATR-buffered (1.5 × ATR₄₈ beyond opposite OR edge).
- **Exits:** Partial scaling at 1R (33%), 2R (33%), 3R (34%). SL moves to break-even after TP1.
- **Risk:** 0.5% account balance per trade. Max 2 concurrent positions, 5 trades/day.
- **Filters:** Opening range width between 5–40 pips (EURUSD) / 6–50 pips (GBPUSD).

---

## 2. Performance Summary

| Metric | EURUSD | GBPUSD |
|--------|--------|--------|
| **Total trades** | 309 | 315 |
| **Winning trades** | 154 | 156 |
| **Losing trades** | 155 | 159 |
| **Win rate** | 49.84% | 49.52% |
| **Total P&L** | +$158.47 | −$847.46 |
| **Return (%)** | +1.58% | −8.47% |
| **Gross profit** | $6,682.18 | $6,489.22 |
| **Gross loss** | $6,523.71 | $7,336.68 |
| **Profit factor** | 1.03 | 0.87 |
| **Sharpe ratio** | 0.17 | −0.96 |
| **Sortino ratio** | 0.19 | −0.97 |
| **Max drawdown** | $827.46 (8.25%) | $1,548.62 (14.79%) |
| **Avg win** | $43.39 | $41.60 |
| **Avg loss** | −$42.09 | −$46.14 |
| **Expectancy/trade** | +$0.51 | −$2.69 |
| **Worst daily loss** | −$59.18 (0.59%) | −$56.03 (0.56%) |

---

## 3. Monthly Equity Curve

### EURUSD Monthly P&L

| Month | P&L ($) |
|-------|---------|
| 2025-01 | −40.70 |
| 2025-02 | +23.91 |
| 2025-03 | −101.25 |
| 2025-04 | −186.86 |
| 2025-05 | −355.87 |
| 2025-06 | −6.74 |
| 2025-07 | +375.78 |
| 2025-08 | +85.92 |
| 2025-09 | +160.78 |
| 2025-10 | +28.77 |
| 2025-11 | +300.19 |
| 2025-12 | −34.16 |
| 2026-01 | −71.30 |
| 2026-02 | −281.77 |
| 2026-03 | −16.31 |
| 2026-04 | +278.08 |

**Pattern:** Strong Q3 2025 (Jul–Sep), strong Nov 2025 and Apr 2026. Weak Q2 2025 (Apr–May) and Feb 2026.

### GBPUSD Monthly P&L

| Month | P&L ($) |
|-------|---------|
| 2025-01 | −64.67 |
| 2025-02 | +103.46 |
| 2025-03 | +80.79 |
| 2025-04 | +16.66 |
| 2025-05 | −37.78 |
| 2025-06 | −164.45 |
| 2025-07 | +261.97 |
| 2025-08 | +124.18 |
| 2025-09 | +78.67 |
| 2025-10 | −479.48 |
| 2025-11 | −239.88 |
| 2025-12 | −46.10 |
| 2026-01 | −468.85 |
| 2026-02 | −70.91 |
| 2026-03 | −181.99 |
| 2026-04 | +240.92 |

**Pattern:** Profitable H1 2025 (Feb–Apr, Jul–Sep). Severe drawdown Oct 2026–Jan 2026 (~$1,368 loss over 4 months). Apr 2026 recovery.

---

## 4. FTMO Feasibility Assessment

| Check | EURUSD | GBPUSD | Limit |
|-------|--------|--------|-------|
| **Daily max loss** | ✅ Pass (0.59%) | ✅ Pass (0.56%) | < 5% |
| **Overall max drawdown** | ✅ Pass (8.25%) | ❌ **BREACH** (14.79%) | < 10% |
| **Profit target** | ❌ Miss (1.58%) | ❌ Miss (−8.47%) | ≥ 8% |
| **Min trades (consistency)** | ✅ Pass (309) | ✅ Pass (315) | ≥ 10 |

### Verdict

- **EURUSD:** Does NOT meet FTMO standards. While drawdown stays within limits, the return (1.58% over 15 months) is far below the 8% profit target. Sharpe of 0.17 is unattractive.
- **GBPUSD:** **Fails FTMO.** Max drawdown of 14.79% breaches the 10% overall limit. Negative return over the period. Sharpe of −0.96 indicates systematic value destruction.

---

## 5. Sample Trades

### EURUSD (first 5)

| Date | Session | Dir | Entry | SL | Risk (pips) | Lots | P&L | Exit | TPs Hit |
|------|---------|-----|-------|----|-------------|------|-----|------|---------|
| 2025-01-02 | LONDON | short | 1.03603 | 1.03796 | 19.3 | 0.26 | +$99.59 | session_end | 3/3 |
| 2025-01-03 | LONDON | long | 1.02867 | 1.02612 | 25.5 | 0.20 | +$1.48 | session_end | 0/3 |
| 2025-01-06 | LONDON | long | 1.03304 | 1.03011 | 29.3 | 0.17 | +$14.33 | stop_loss | 1/3 |
| 2025-01-07 | LONDON | long | 1.04264 | 1.03865 | 39.9 | 0.13 | −$52.92 | stop_loss | 0/3 |
| 2025-01-08 | LONDON | short | 1.03265 | 1.03607 | 34.2 | 0.15 | +$41.21 | session_end | 1/3 |

### GBPUSD (first 5)

| Date | Session | Dir | Entry | SL | Risk (pips) | Lots | P&L | Exit | TPs Hit |
|------|---------|-----|-------|----|-------------|------|-----|------|---------|
| 2025-01-02 | LONDON | short | 1.25176 | 1.25423 | 24.7 | 0.20 | +$99.79 | session_end | 3/3 |
| 2025-01-03 | LONDON | long | 1.24088 | 1.23770 | 31.8 | 0.16 | −$6.90 | session_end | 0/3 |
| 2025-01-06 | LONDON | long | 1.24590 | 1.24284 | 30.6 | 0.16 | +$14.42 | stop_loss | 1/3 |
| 2025-01-07 | LONDON | short | 1.25345 | 1.25741 | 39.6 | 0.13 | −$52.90 | stop_loss | 0/3 |
| 2025-01-08 | LONDON | short | 1.24606 | 1.25004 | 39.8 | 0.13 | +$100.60 | session_end | 3/3 |

---

## 6. Observations & Recommendations

### Strategy Behavior

1. **Win rate near 50%** — The ORB strategy as configured is essentially a coin flip on direction. The edge (if any) comes from the asymmetric payoff via partial scaling.
2. **EURUSD marginally profitable** — Profit factor of 1.03 means the strategy barely covers costs. Any increase in spread or slippage would push it negative.
3. **GBPUSD value-destroying** — The wider breakout threshold (2.5 pips vs 2.0) isn't enough to compensate for GBPUSD's higher volatility. The strategy gets chopped up in ranging conditions.
4. **Session dependence** — The majority of signals come from the London session. NY session contributes fewer trades (shorter range window).
5. **TP1 (break-even) effect** — Moving SL to break-even after TP1 reduces gross losses but caps upside on trades that would have run further.

### Comparison to Registry Strategies

The existing `session_range_mean_reversion` and `volatility_squeeze` strategies in the Ayumi registry are likely better suited for these pairs on M15. ORB as a standalone strategy on M15 forex lacks the momentum persistence seen in equity or commodity markets.

### Recommendations

- **Do not deploy ORB standalone** on EURUSD/GBPUSD M15 without significant enhancement.
- **Consider M5 data** if it becomes available — ORB benefits from finer granularity for range construction and breakout detection.
- **Test on XAUUSD** — Gold's stronger trending nature may suit ORB better than forex pairs.
- **Explore volatility-regime filtering** — Only take ORB signals when ATR percentile is elevated (momentum regime).
- **GBPUSD max range width** of 50 pips may still be too permissive — tighter filter (35 pips) might reduce false breakouts.

---

## 7. Config Validation

Both config files pass YAML schema validation:

- ✅ All required fields present (account, risk, instrument, strategy, backtest, ftmo)
- ✅ Session windows are valid UTC time ranges
- ✅ Partial exit percentages sum to 1.0 (0.33 + 0.33 + 0.34)
- ✅ Risk parameters within FTMO constraints
- ✅ Data files exist at specified paths
- ✅ See `tests/test_orb_config_validation.py` for automated validation

---

## Appendix: Methodology

- **Data:** M15 OHLCV bars from existing CSV files, timezone-converted from ET to UTC by `CsvDataLoader`.
- **Bar count:** 31,671 bars per symbol (2025-01-01 to 2026-04-10).
- **Backtest engine:** Custom ORB runner implementing the YAML config spec. Uses existing `CsvDataLoader` for data ingestion. Does NOT use `SimpleBacktestEngine` (no ORB strategy adapter exists).
- **Costs:** Spread (1.5 pips round-trip), commission ($3.5/lot round-trip).
- **Sharpe/Sortino:** Annualized assuming 252 trading days. Per-trade returns used (not per-bar).
- **Max drawdown:** Computed from equity curve (peak-to-trough).
- **FTMO checks:** Static thresholds from config (daily 5%, overall 10%, target 8%).
