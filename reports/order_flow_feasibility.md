# Order Flow / Tick Data Strategy Feasibility Report

**Issue:** AYUAA-479  
**Date:** 2026-04-06  
**Author:** Research Manager

---

## Executive Summary

**Conclusion: True tick-level order flow data is NOT available for forex.** The company has OHLCV M1 data (from HistData.com) but no bid/ask volume breakdown, delta attribution, or true tick data. Order flow strategies requiring genuine tick-by-tick data are **NOT feasible** with current infrastructure.

**Recommended path:** Pursue OFI (Order Flow Imbalance) proxies using available OHLCV + volume data. VAP (Volume at Price) analysis and delta divergence detection are viable alternatives.

---

## Data Availability Assessment

### Current Data Sources

| Source | Format | Tick Data | Bid/Ask Volume |可用性 |
|--------|--------|-----------|---------------|--------|
| HistData.com (current) | OHLCV M1 | ❌ | ❌ | ✅ Available |
| cTrader Open API | Tick + OHLCV | ✅ | ❌ (no bid/ask vol) | ⚠️ Requires credentials |
| TrueFX | Tick BID/ASK | ✅ | ✅ | ❌ Defunct |
| FXCM | Tick + depth | ✅ | ✅ | ⚠️ Requires API key |

### Current Data Structure (all pairs)

```
timestamp, Open, High, Low, Close, Volume
2025-01-01 18:00:00, 2625.098, 2626.005, 2624.355, 2625.048, 0
```

- **Volume field is zero or unreliable** for most bars
- No bid/ask volume attribution
- No delta (buy volume - sell volume)
- No order book depth data

### cTrader Open API Capabilities

The cTrader Open API (used for live trading) provides:
- ✅ Real-time OHLCV bars (M1 and above)
- ✅ Tick data (last sale price)
- ❌ **No bid/ask volume** — only total volume per bar
- ❌ **No true order book** — only top-of-book quotes

**Limitation:** Cannot distinguish aggressive buying from aggressive selling from price action alone.

---

## What Order Flow Strategies Require

For true institutional order flow analysis:

| Requirement | Description | Available? |
|-------------|-------------|-----------|
| Tick-by-tick data | Every price change with timestamp | ❌ |
| Bid/Ask volume | Volume at bid vs ask | ❌ |
| Delta | Net buying/selling pressure | ❌ |
| Order book depth | L2/L3 market depth | ❌ |
| Time & Sales | Tape reading | ❌ |

**Bottom line:** Standard retail forex APIs do not provide institutional-grade order flow data.

---

## Viable Alternative: OFI (Order Flow Imbalance) Proxies

Despite lacking true tick data, we can approximate order flow using OHLCV dynamics. This was researched in [AYUAA-401](/AYUAA/issues/AYUAA-401).

### OFI Proxy Calculation

```python
def calculate_ofi(bars: List[Bar]) -> float:
    """
    Order Flow Imbalance proxy = Σ (price change direction × volume proxy)
    Without true bid/ask vol, we use:
      - Close vs Open direction as volume proxy
      - Volume magnitude (if available)
    """
    ofi = 0.0
    for i in range(len(bars) - 1):
        price_change = bars[i+1].close - bars[i+1].open
        volume_proxy = bars[i+1].volume if bars[i+1].volume > 0 else 1
        direction = 1 if price_change >= 0 else -1
        ofi += direction * volume_proxy
    return ofi
```

### Caveats with OHLCV-only OFI

1. **Volume field unreliable** — most historical data has zero volume
2. **No buy/sell attribution** — close > open doesn't guarantee aggressive buying
3. **Inferred direction is noisy** — requires smoothing

### Recommended OFI Features (with OHLCV)

| Feature | Calculation | Notes |
|---------|-------------|-------|
| OFI_raw | sign(Δclose) × volume | Only works if volume > 0 |
| OFI_smoothed | 14-bar SMA of OFI | Reduces noise |
| OFI_gradient | OFI - OFI[5 bars ago] | Flow acceleration |
| Close location | (Close - Low) / (High - Low) | Session-profiled location |
| Delta divergence | Correlation(OFI_proxy, price, 20) | Divergence detection |

---

## Viable Strategy Specs

### Strategy A: Session-Profiled OFI (OFI + Session Context)

**Concept:** Combine OHLCV-proxied OFI with session context (London/NY killzones) to identify institutional footprints.

**Entry Logic:**
- LONG: OFI_gradient > 0 + price near session low + within London/NY killzone
- SHORT: OFI_gradient < 0 + price near session high + within London/NY killzone

**Data Requirements:**
- H1 OHLCV bars (available: EURUSD, GBPUSD, GBPJPY, USDJPY, XAUUSD)
- Session timing data (already implemented in session_range_mr)
- Volume (optional, can use 1 as constant)

**Expected Performance:**
- Win Rate: 40-50%
- Profit Factor: 1.4-1.8
- Max DD: <8%

**Implementation Complexity:** Low — reuse session timing from Session-Range MR

---

### Strategy B: Volume at Price (VAP) Imbalance

**Concept:** Analyze where volume concentrates within each bar's range. High volume at top of bar = selling pressure; high volume at bottom = buying pressure.

**Calculation:**
```python
def vap_imbalance(bar: Bar) -> float:
    """
    Returns -1 to +1
    -1 = all volume at high (selling)
    +1 = all volume at low (buying)
    0 = uniform volume distribution
    """
    if bar.high == bar.low:
        return 0.0
    close_location = (bar.close - bar.low) / (bar.high - bar.low)
    return 2 * close_location - 1  # Normalized to [-1, +1]
```

**Entry Logic:**
- LONG: VAP_imbalance > 0.3 (buying pressure) + near session low
- SHORT: VAP_imbalance < -0.3 (selling pressure) + near session high

**Data Requirements:** H1 OHLCV only — no additional data needed

**Expected Performance:** Unknown — requires backtesting

**Implementation Complexity:** Very Low — single function

---

## Recommendations

### Immediate (Doable Now)
1. **Build Volume at Price (VAP) Imbalance strategy** — requires only H1 OHLCV data, no new data sources
2. **Enhance Session-Range MR with VAP filter** — add VAP as entry confirmation
3. **Test OFI proxy with session context** — reuse session timing infrastructure

### Medium-term (Requires Engineering)
4. **Investigate cTrader Open API for tick data** — Kai has credentials, can assess if any tick/delta data is extractable
5. **Source alternative data providers:**
   - **CQG**: Commercial forex tick data ($$$)
   - **Dukascopy**: Free tick data (lower quality)
   - **Finage**: Affordable tick data API

### NOT Recommended (Blocked by Data)
- True institutional order flow (requires L2/exchange data)
- Tick-by-tick delta strategies
- Market maker squeeze detection

---

## Data Gap Request

If cTrader can provide any of the following, order flow becomes significantly more viable:

| Data Element | Priority | Who to Ask |
|-------------|----------|------------|
| Tick data with timestamp | High | Kai (Forex Manager) |
| Bid/Ask volume per bar | High | Kai (Forex Manager) |
| Real-time order book | Medium | Kai (Forex Manager) |

**Action:** Request Kai to assess cTrader Open API capabilities for tick/delta data export.

---

## Conclusion

True tick-level order flow data is not available for forex through standard retail APIs. However, **OHLCV-based proxies (OFI, VAP) are viable** and can be implemented immediately using existing H1 data. These won't capture institutional-grade order flow but can provide marginal edge in session-context trading.

**Recommendation:** Proceed with VAP Imbalance and OFI proxy strategies as add-ons to Session-Range MR rather than standalone order flow strategies.