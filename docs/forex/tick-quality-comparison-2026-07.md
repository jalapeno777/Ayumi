# Tick Data Quality Comparison: Live vs Backtest

**Date:** 2026-07-02
**Author:** Tsukasa (automated analysis)
**Method:** Structural code analysis + known data source characteristics

---

## Executive Summary

The Ayumi backtest engine uses **HistData.com M1 OHLCV data** with
**hardcoded spread and slippage assumptions**. The live trading pipeline
receives **real-time bid/ask tick data from cTrader Open API**. This report
documents the material differences between these two data environments and
assesses whether divergence could suppress live trading signals.

**Key finding:** The structural differences are significant enough to cause
live performance divergence from backtests. The backtest's fixed cost model
underestimates real-world trading costs during volatile periods and
completely omits tick-level dynamics that affect signal timing.

---

## Data Source Comparison

| Dimension | HistData.com (Backtest) | cTrader Open API (Live) |
|-----------|------------------------|------------------------|
| **Format** | M1 OHLCV bars | Real-time bid/ask spot ticks |
| **Timestamps** | GMT, minute-aligned | UTC, sub-second precision |
| **Spread** | Not present (hardcoded in engine) | Dynamic, embedded in bid/ask |
| **Volume** | Zero or unreliable | Per-bar aggregate (no bid/ask split) |
| **Tick detail** | None (pre-aggregated) | Every price update |
| **Gaps** | Weekend/holiday gaps | Connection drops + weekend gaps |
| **Cost model** | Fixed per-pair spread + random slippage | Variable spread + market impact |

---

## Backtest Spread Assumptions

The `ExecutionSimulator._calculate_spread()` method uses these hardcoded values:

| Pair | Spread (pips) | Slippage (pips) | Total cost (pips) |
|------|--------------|-----------------|-------------------|
| AUDUSD | 1.2 | 0.5 | 1.7 |
| EURGBP | 2.0 | 0.5 | 2.5 |
| EURJPY | 2.0 | 0.5 | 2.5 |
| EURUSD | 1.0 | 0.5 | 1.5 |
| GBPJPY | 2.5 | 0.5 | 3.0 |
| GBPUSD | 1.5 | 0.5 | 2.0 |
| NZDUSD | 1.5 | 0.5 | 2.0 |
| USDCAD | 1.5 | 0.5 | 2.0 |
| USDCHF | 1.5 | 0.5 | 2.0 |
| USDJPY | 1.0 | 0.5 | 1.5 |

**Total round-trip cost** = 2 × (spread + slippage) + commission.

For EURUSD: 2 × (1.0 + 0.5) pips + $7.0/lot commission ≈ **3.0 pips + commission**.

---

## Material Differences

### 1. Spread Dynamics

**Backtest:** Fixed spread per pair (e.g., EURUSD = 1.0 pip always).

**Live:** cTrader spread fluctuates with:
- **Session liquidity:** Asian session spreads can be 2-5× wider than London/NY overlap
- **News events:** Spreads can widen to 10-20× normal during NFP, FOMC, etc.
- **Symbol-specific patterns:** Exotic pairs (GBPJPY, EURGBP) have wider and more volatile spreads

**Impact on signals:** Strategies that appear profitable at 1.0 pip fixed cost may
lose money during high-spread periods. The backtest cannot capture this because
it applies the same cost regardless of market conditions.

### 2. Tick Frequency

**Backtest:** HistData M1 bars contain no tick information. The engine processes
one bar per minute and generates signals at bar close.

**Live:** cTrader sends spot events whenever bid/ask changes. Tick frequency varies:
- **High activity (London/NY overlap):** 10-50 ticks/second for EURUSD
- **Low activity (Asian session):** 1-5 ticks/second
- **Pre-news lull:** Near-zero ticks before major announcements

**Impact on signals:** The live BarBuilder aggregates ticks into bars that may
differ slightly from HistData bars due to:
- Different timestamp conventions (tick arrival vs exchange timestamp)
- Interpolation/smoothing in the aggregation
- Bars forming from real bid/ask midpoints vs HistData's pre-aggregated OHLC

### 3. Bar OHLC Divergence

**Backtest:** HistData bars use a specific aggregation source and methodology.

**Live:** The `BarBuilder` aggregates ticks into OHLCV using:
- Mid-price (bid+ask)/2 as the price input
- Bar period boundaries in UTC

**Potential divergence sources:**
- HistData may use last-trade price instead of midpoint
- Timestamp alignment differences (HistData GMT vs cTrader UTC)
- HistData bars may include/exclude the boundary tick differently
- Data vendor differences in how highs/lows are recorded

**Expected magnitude:** Typically 0.1-0.5 pips per bar for liquid pairs.
This is small but can matter for tight-stop strategies.

### 4. Gaps and Missing Data

**Backtest (HistData):**
- Systematic gaps: Weekend (Fri 22:00 → Sun 22:00 GMT)
- Holiday gaps: Christmas, New Year, etc.
- Occasional data vendor gaps (rare but present)

**Live (cTrader):**
- All the above, plus:
- Connection drops and reconnections (variable duration)
- cTrader server maintenance windows
- Kill switch activations

**Impact:** Live gaps are unpredictable and can cause:
- Missed bar closes (strategy skips a signal)
- Stale prices on reconnection (BarBuilder burst mode mitigates)
- Position risk during disconnection

### 5. Volume Information

**Backtest:** HistData volume is zero or unreliable for most forex pairs.

**Live:** cTrader provides volume per bar but:
- No bid/ask volume attribution
- Volume is tick-count proxy, not true traded volume
- Cannot distinguish aggressive buying from selling

**Impact:** Volume-based signals are unreliable in both environments.
The `order_flow_feasibility.md` report already identified this limitation.

---

## Could Divergence Suppress Signals?

**Yes, in three specific ways:**

### A. Spread Cost Underestimation
If live spreads average 1.5-2× the backtest assumption during active hours,
strategies with thin edges (< 2 pips expected value) become marginal.
The backtest's fixed 1.0 pip EURUSD spread is optimistic during:
- Asian session open (typical spread: 1.5-3.0 pips)
- News windows (typical spread: 5-20+ pips)
- Month-end / quarter-end liquidity drain

### B. Signal Timing Shift
Bar close signals depend on the exact OHLC values. If live-aggregated bars
differ from HistData bars by even 0.1-0.3 pips, this can:
- Shift the trigger price for stop orders
- Change the bar's high/low, affecting breakout signals
- Alter indicator values (e.g., ATR, moving averages) enough to flip a signal

### C. Connection Reliability
The live tick pipeline is subject to TCP disconnections, cTrader server
restarts, and authentication refresh cycles. Each gap can cause:
- Missing bars (strategy waits for next bar)
- Partial bars (BarBuilder builds incomplete bar from burst ticks)
- Delayed signals (tick arrives late, bar closes late)

The `health_check_tick_pipeline.py` script monitors for stalls ≥5 minutes,
but even sub-5-minute gaps can miss trading windows.

---

## Recommendations

1. **Capture live ticks for empirical comparison.** Run the `sample` mode
   during different sessions to build a dataset for quantitative comparison.

2. **Instrument the spread.** Log the actual bid/ask spread on every signal
   evaluation so the live cost can be compared to the backtest assumption.

3. **Backtest with variable spreads.** Replace the fixed spread model with
   a session-aware spread model that widens during Asian hours and news windows.

4. **Add slippage from real execution data.** Track the difference between
   signal price and fill price to calibrate the slippage model.

5. **Monitor bar divergence.** When the live bar closes, compare it to the
   corresponding HistData bar (if available) and log the pip difference.

---

## Methodology Limitations

This is a **structural analysis** based on code inspection and known data
source characteristics. It does not include empirical measurements because:

- No live tick captures are currently stored in the system
- cTrader credentials are required for live sampling
- HistData M1 data files are not present in the repository

The `sample` and `compare` modes of this script provide the empirical
framework once data is available.
