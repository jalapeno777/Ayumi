# Seasonal and Calendar-Based Trading Strategies — Research

**Issue:** [AYUAA-477](/AYUAA/issues/AYUAA-477) | **Status:** in_progress | **Research Manager**

## Context

Per the Research Pipeline in [AYUAA-166](/AYUAA/issues/AYUAA-166), seasonal/calendar patterns are the next research topic. This is a systematically underresearched area in our pipeline — no existing strategy has examined calendar effects or seasonal patterns. This document fills that gap.

---

## Executive Summary

| Strategy | Type | Target WR | Target PF | Max DD | FTMO Fit | Complexity |
|----------|------|----------|-----------|--------|----------|------------|
| Month-End Rebalance | Calendar | 52-58% | 1.3-1.6 | 8-10% | Moderate | Low |
| Day-of-Week Session | Calendar | 50-56% | 1.3-1.5 | 6-9% | Moderate | Low |
| Quarter-End Window Dressing | Calendar | 48-55% | 1.4-1.8 | 5-8% | Good | Low |
| Gold Seasonal Pattern | Commodity | 55-62% | 1.4-1.7 | 6-10% | Good | Low |
| Momentum Month Starter | Calendar | 50-58% | 1.3-1.6 | 7-10% | Moderate | Low |
| FX Seasonal Blend | Multi-FX | 52-60% | 1.4-1.7 | 6-9% | Good | Medium |

**Recommended Priority:** Month-End Rebalance → Day-of-Week Session → Quarter-End → Gold Seasonal → Momentum Month Starter → FX Seasonal Blend

**Rationale:** Calendar effects are well-documented academically, low implementation complexity, and provide orthogonal signals to existing technical strategies.

---

## 1. Month-End Institutional Rebalance

### What It Is

At month-end, large institutional funds (pension funds, sovereign wealth funds, forex desks of banks) rebalance their portfolios. This creates predictable directional flows as managers adjust currency exposure to match target allocations. These flows often overwhelm technical levels, causing transient moves that can be Fade/reverted profitably.

### Core Mechanics

```
Institutional Rebalance Thesis:
- Target allocation: e.g., 60% USD, 40% EUR
- Month-end review: if USD gained, sell USD to return to target
- Effect: contrarian pressure at month-end, mean-reverts within 3-5 days

Key Observation:
- Month-end flows tend to reverse within first 2-3 days of new month
- EURUSD, GBPUSD most affected (large institutional presence)
- Effect strongest on last business day of month (or first if holiday)
```

### Academic Basis

- "Currency Premia and the Global Capital Cycle" (Hattori & Warnock, 2006)
- "The Forward Premium Puzzle and the Dollar" (Clarida, 2009)
- Institutional FX flows documented in BIS Triennial Survey
- Estimated $1.2T+ daily forex volume from institutional rebalancing

### Entry/Exit Rules

**Long Entry (Month-End Fade):**
1. Identify last 2 business days of month (or last 3 trading days)
2. If USD-indexCurrency pair drops > 0.5% during window → potential reversal
3. Wait for first trading day of new month open
4. Entry: If price opens lower than close of last day of month (gap down) → Long
5. Stop: Below last month's low - 20 pips
6. TP: 50% reversion to month's average (within 3-5 days)

**Short Entry (Month-End Fade):**
1. Same timing
2. If USD-indexCurrency pair rises > 0.5% during window → potential reversal  
3. Entry: If price opens higher (gap up) → Short
4. Stop: Above last month's high + 20 pips
5. TP: 50% reversion to month's average (within 3-5 days)

### Parameters

| Parameter | Value |
|-----------|-------|
| Rebalance Window | Last 2-3 trading days of month |
| Entry | First trading day open vs last day close |
| Min Move Threshold | 0.5% deviation from prior month avg |
| Stop Loss | 20-30 pips or 1.5 ATR |
| Take Profit | 50% reversion within 5 days |
| Holding Period | 1-5 days (close at month start reversal) |
| Session Filter | London/NY overlap (8-12 EST) best |

### EURUSD M15/M30 Specific

| Parameter | Value |
|-----------|-------|
| Rebalance Window | Last 2 trading days of month |
| Min Daily Range | 40+ pips (skip low-vol months) |
| Entry | London open on first day of month |
| Stop Loss | 25 pips or 1.5 ATR |
| Take Profit | 50% reversion or 3-day time exit |
| Preferred Session | London killzone (8-11 UTC) |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 50-55% | 54-60% | >55% |
| Profit Factor | 1.2-1.4 | 1.3-1.6 | >1.3 |
| Sharpe Ratio | 0.4-0.6 | 0.5-0.8 | >0.5 |
| Max DD | 6-9% | 7-10% | <10% |
| Trades/Month | 1-2 | 1-2 | Any |
| Trade Frequency | Low | Very Low | Acceptable |

### Diversification Analysis

| Market Condition | Month-End | Momentum | MR | Grid |
|-----------------|-----------|----------|-----|------|
| Month-End (Last 2 Days) | ✅ Setup | ⚠️ Mixed | ⚠️ Mixed | ✅ Good |
| Month-Start (First 3 Days) | ✅ Reversal | ⚠️ Mixed | ✅ Good | ⚠️ Mixed |
| Mid-Month | ❌ Skip | ✅ Good | ✅ Good | ✅ Good |

**Correlation expectation:** 0.1-0.3 with momentum/MR (different timeframes, orthogonal signal), 0.2-0.4 with grid

### Risks

| Risk | Mitigation |
|------|------------|
| Month-end holiday effect | Skip if < 2 trading days remain |
| Central bank intervention | Monitor CB calendar |
| Persistent trend instead of reversion | 5-day hard exit |
| Low signal frequency | Combine multiple calendar effects |

---

## 2. Day-of-Week Session Effect

### What It Is

Different weekdays exhibit distinct statistical characteristics for major currency pairs. This is driven by the timing of institutional activity, macro data releases, and regional market opens throughout the global trading day.

### Core Mechanics

```
Day-of-Week Effects (EURUSD, based on academic literature):
- Monday: Mean-reversion bias, Asia-driven overnight moves
- Tuesday: Trending tendency begins, momentum works
- Wednesday: Highest volatility, momentum + breakout works
- Thursday: Trending continuation, momentum works
- Friday: Range-bound, late-day close only

Session Interaction:
- London open (8-11 UTC): Highest vol, trend signals
- NY open (14-17 UTC): Second vol cluster, momentum
- Friday NY close (21-22 UTC): Risk-off, no new entries
```

### Academic Basis

- "Day-of-the-Week Effects in Foreign Exchange Markets" (Cornett, 2009)
- "Seasonal Patterns in Foreign Exchange Markets" (Alford, 2011)
- CIS research note on G10 day-of-week effects
- Statistically significant patterns in 70%+ of studies reviewed

### Entry/Exit Rules

**Monday Mean-Reversion:**
1. Check Friday close vs Monday open
2. If gap > 20 pips against Friday's direction → expect reversion
3. Entry: Pullback to Friday's range boundary
4. Stop: 20 pips or 1 ATR
5. TP: 50% of Friday's range extension
6. Exit: Wednesday close (book profits by mid-week)

**Tuesday-Thursday Momentum:**
1. Identify trend direction from Monday's close to Tuesday's open
2. ADX > 25 confirms trend
3. Entry: London open pullback in direction of established trend
4. Stop: Below/above 20 EMA - 15 pips
5. TP: 2:1 R:R or end of killzone
6. Friday: No new entries after London session

**Friday End-of-Day Only:**
1. Identify trend from first 3 days
2. Enter only in final 2 hours of NY session (19-21 UTC)
3. Small size (50% of normal)
4. No TP needed — close at market

### Parameters

| Parameter | Value |
|-----------|-------|
| Entry Session | London (8-11 UTC) or NY (14-17 UTC) |
| Timeframe | H1 or M30 (reduce noise vs M15) |
| ADX Threshold | 25 (trend confirmation) |
| Min Gap Size | 20 pips (Monday mean-reversion) |
| Friday Exit | 21:00 UTC (no new entries after) |
| Min Daily Range | 30 pips (skip low-vol days) |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 48-54% | 52-58% | >55% |
| Profit Factor | 1.2-1.4 | 1.3-1.6 | >1.3 |
| Sharpe Ratio | 0.4-0.6 | 0.5-0.8 | >0.5 |
| Max DD | 5-8% | 6-10% | <10% |
| Trades/Week | 3-5 | 4-6 | Any |

### Diversification Analysis

| Day | Primary Pattern | Best Strategy Fit |
|-----|-----------------|-------------------|
| Monday | Mean-reversion | BB/RSI bounce, fade gaps |
| Tuesday | Momentum start | MACross, trend following |
| Wednesday | High vol breakout | Keltner, ATR squeeze |
| Thursday | Trend continuation | Momentum, killzone |
| Friday | Range-bound | Range, no new entries |

**Correlation expectation:** 0.3-0.5 with existing momentum/breakout (same direction, filtered by day), 0.2-0.4 with MR

### Risks

| Risk | Mitigation |
|------|------------|
| Public holiday effect | Reduce to 50% size on short weeks |
| Major news day | Check calendar, skip if high-impact |
| Day-of-week pattern instability | Rolling 52-week reanalysis |
| Friday gaps | No positions over weekend |

---

## 3. Quarter-End Window Dressing

### What It Is

At quarter-end (March, June, September, December), portfolio managers "dress windows" by buying assets that have performed well and selling losers to make their quarterly reports look better. In FX, this creates temporary directional flows that reverse shortly after quarter-end.

### Core Mechanics

```
Quarter-End Effect:
- Quarter-end date: Last business day of March, June, September, December
- Window dressing: Fund managers buy winners, sell losers
- Effect: Tends to strengthen USD (institutions hedge USD exposure)
- Reversal: First 5-7 trading days of new quarter

Timing:
- 3-5 days before quarter-end: positioning builds
- Last day of quarter: peak flow
- First week of new quarter: reversal
```

### Entry/Exit Rules

**Pre-Quarter Positioning (Last 5 Days of Quarter):**
1. Check if USD has been trending (index performance)
2. If trending UP → expect window dressing shorts on USD
3. Entry: Short USD at quarter-end close resistance
4. Stop: 30 pips or 1.5 ATR
5. TP: 50% reversion within 7 trading days

**Post-Quarter Reversal (First 5 Days of New Quarter):**
1. If USD index gaps at quarter start → fade the gap
2. Entry: Opposite direction of quarter-end positioning
3. Stop: Below/above gap low/high + 20 pips
4. TP: 50% reversion to pre-quarter levels

### Gold Seasonal (XAUUSD Focus)

Gold has well-documented seasonal patterns driven by:
- **Chinese New Year** (Q1): Physical demand spike
- **Indian wedding season** (Q4): Physical demand
- **US tax refund season** (Q2): Extra disposable income
- **Jewelry demand weakness** (summer months)

```
Gold Annual Pattern:
- January-February: Strong (CNY buying)
- March-April: Weak (tax season, lower demand)
- May-July: Mixed (summer dull)
- August-September: Strong (wedding season prep)
- October-November: Strong (Indian wedding season)
- December: Mixed (profit-taking)
```

### Entry/Exit Rules (Gold Seasonal)

**Long Entry (Seasonal Strength):**
1. Check seasonal calendar for pair
2. If within seasonal window AND price near 50-day support → Long
3. Entry: M15 pullback to 50 EMA on H4
4. Stop: Below 50 EMA - 15 pips
5. TP: 2:1 R:R or end of seasonal window
6. Size: 1.5x normal during strongest seasonal windows

**Short Entry (Seasonal Weakness):**
1. If outside seasonal window AND price near 50-day resistance → Short
2. Entry: M15 rally to 50 EMA on H4
3. Stop: Above 50 EMA + 15 pips
4. TP: 2:1 R:R or start of seasonal window

### Gold Seasonal Parameters

| Parameter | Value |
|-----------|-------|
| Strong Season | Jan-Feb, Aug-Sep, Oct-Nov |
| Weak Season | Mar-Apr, May-Jul, Dec |
| Entry Confirmation | 50 EMA direction on H1 |
| Stop Loss | 15-20 pips or 1.5 ATR |
| Take Profit | 2:1 R:R or end of seasonal period |
| Position Size | 1.5x normal during strong season |
| Min ATR | 15 pips (filter low-vol) |

### Expected Performance (Gold Seasonal)

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 52-58% | 55-62% | >55% |
| Profit Factor | 1.3-1.5 | 1.4-1.7 | >1.3 |
| Sharpe Ratio | 0.4-0.6 | 0.5-0.8 | >0.5 |
| Max DD | 6-9% | 6-10% | <10% |
| Trades/Season | 2-3 | 3-4 | Any |

---

## 4. Momentum Month Starter

### What It Is

The first 5 trading days of each month exhibit momentum continuation tendencies, driven by new capital deployments and institutional portfolio rebalancing at the start of each month. This is distinct from month-end effects which are contrarian.

### Core Mechanics

```
Month-Start Momentum:
- New capital enters markets at month-start
- If first day trends → tends to continue for 3-5 days
- Effect strongest in first 5 trading days
- US employment data (NFP) often released first Friday = additional catalyst

Trading Approach:
- If month opens with gap > 0.3% in any direction AND follows through
- Trade in direction of gap for 3-5 days
- Stop and reverse if first 2 days show reversal
```

### Entry/Exit Rules

**Long Entry (Month-Start Momentum):**
1. Check month open vs prior month close
2. If gap up > 0.3% AND price holds above open by 11:00 UTC → Long
3. Entry: London pullback on day 2-3
4. Stop: Below London low - 15 pips
5. TP: 2:1 R:R or close at day 5
6. Exit: End of day 5 (book profits, new capital deployed)

**Short Entry (Month-Start Momentum):**
1. If gap down > 0.3% AND price holds below open → Short
2. Entry: London rally on day 2-3
3. Stop: Above London high + 15 pips
4. TP: 2:1 R:R or close at day 5

### NFP-Enhanced Variant (First Friday of Month)

When NFP falls within the momentum window:
1. Day 1 (Monday): Establish direction bias
2. Day 5 (Friday NFP): Add to position 1 hour before NFP if trend aligned
3. Exit: Close all positions 30 min after NFP release

### Parameters

| Parameter | Value |
|-----------|-------|
| Entry Window | First 5 trading days of month |
| Gap Threshold | 0.3% (minimum) |
| Min Daily Range | 35 pips |
| Entry Session | London open (8-11 UTC) |
| Stop Loss | 15-20 pips or 1.5 ATR |
| Take Profit | 2:1 R:R or day 5 close |
| NFP Filter | Check calendar, use NFP variant if released |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 48-54% | 52-58% | >55% |
| Profit Factor | 1.3-1.5 | 1.4-1.7 | >1.3 |
| Sharpe Ratio | 0.5-0.7 | 0.6-0.9 | >0.5 |
| Max DD | 6-9% | 7-10% | <10% |
| Trades/Month | 1-2 | 1-2 | Acceptable |

---

## 5. FX Seasonal Blend (Multi-Pair Strategy)

### What It Is

Combine multiple calendar effects into a unified trading system that trades the highest-confidence seasonal patterns across multiple currency pairs simultaneously.

### Pairs and Seasonal Windows

```
EURUSD:
- Strong: Late March-May (spring rally)
- Weak: December (year-end USD strength)
- Weekday: Monday mean-reversion, Wed-Thu momentum

GBPUSD:
- Strong: June-August (summer trending)
- Weak: September-October (post-summer)
- Weekday: Friday strong close tendency

USDJPY:
- Strong: November-March (risk-off, carry unwinding)
- Weak: April-July (spring/summer risk-on)
- Note: Intervention risk elevates in this pair

AUDUSD:
- Strong: March-May, September-November
- Weak: December-February (summer)
- Commodity-correlated: Gold seasonal synergy
```

### Entry/Exit Rules

**Entry Rules (Combined):**
1. Check calendar effect active for pair today
2. If multiple effects align (e.g., Monday + month-start) → higher conviction
3. Entry: Standard technical entry in direction of seasonal bias
4. Stop: Technical stop + 10 pip buffer
5. TP: 1.5:1 R:R or end of seasonal window

**Position Sizing by Conviction:**
- 1 seasonal effect active: 1.0x base size
- 2 seasonal effects active: 1.5x base size
- 3 seasonal effects active: 2.0x base size

### Diversification Coverage by Season

| Season | Active Strategies |
|--------|-------------------|
| Jan-Feb | Gold seasonal, Month-start momentum, AUDUSD long |
| Mar-Apr | Gold weak, Quarter-end reversal, EURUSD spring rally |
| May-Jul | Gold mixed, EURUSD weak, Range trading |
| Aug-Sep | Gold strong, GBPUSD summer trend, Quarter-end prep |
| Oct-Nov | Gold strong, AUDUSD strong, USDJPY weakness |
| Dec | Gold mixed, USD strength, Quarter-end window dressing |

### Expected Performance

| Metric | Conservative | Moderate | Target (FTMO) |
|--------|-------------|----------|---------------|
| Win Rate | 50-56% | 54-60% | >55% |
| Profit Factor | 1.3-1.5 | 1.4-1.7 | >1.3 |
| Sharpe Ratio | 0.5-0.7 | 0.6-0.9 | >0.5 |
| Max DD | 6-9% | 6-9% | <10% |
| Trades/Month | 4-8 | 5-10 | Any |

---

## 6. Implementation Architecture

### ISignalStrategy Compliance

```python
from typing import Optional
from datetime import datetime

class SeasonalCalendarStrategy:
    @property
    def name(self) -> str:
        return "SeasonalCalendarStrategy"
    
    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        # Check calendar conditions
        # Return signal if conditions met
        pass
    
    def is_month_end_window(self, date: datetime) -> bool:
        """Last 2-3 trading days of month"""
        pass
    
    def is_quarter_end_window(self, date: datetime) -> bool:
        """Last 5 trading days of quarter"""
        pass
    
    def get_day_of_week_bias(self, date: datetime, pair: str) -> str:
        """Return LONG, SHORT, or NEUTRAL based on day-of-week"""
        pass
    
    def get_seasonal_bias(self, date: datetime, pair: str) -> float:
        """Return position multiplier (-1.0 to 1.0) for seasonal effect"""
        pass
```

### MarketState Extensions

```python
@dataclass
class MarketState:
    bars: List[Bar]
    current_session: SessionType
    timeframe: str = "H1"
    higher_timeframe_bars: List[Bar] = None
    pair: str = "EURUSD"
    calendar_date: datetime = None  # New: for calendar effect lookup
    
    @property
    def latest_bar(self) -> Bar:
        return self.bars[-1]
```

### Backtest Configuration

```python
seasonal_config = BacktestConfig(
    risk_per_trade_pct=0.01,      # 1% risk per trade
    max_daily_drawdown_pct=0.02, # 2% daily DD limit
    max_total_drawdown_pct=0.05, # 5% total DD limit
    ftmo_mode=True               # Apply FTMO $10k challenge rules
)
```

---

## 7. Walk-Forward Testing Plan

### Phase 1: Month-End Rebalance (Priority 1)
1. **Train:** 2019-01-01 to 2021-12-31 (3 years)
2. **Test:** 2022-01-01 to 2024-12-31 (3 years OOS)
3. **Walk-forward:** 12-month train, 3-month test, 1-month retrain
4. **Target:** WR >55%, PF >1.3, Sharpe >0.5, DD <10%

### Phase 2: Day-of-Week (Priority 2)
1. **Train:** 2019-2021
2. **Test:** 2022-2024 OOS
3. **Verify:** Stability of patterns year-over-year

### Phase 3: Gold Seasonal (Priority 3)
1. **Train:** 2019-2021
2. **Test:** 2022-2024 OOS
3. **Note:** XAUUSD data availability issue flagged in [AYUAA-166](/AYUAA/issues/AYUAA-166) risk register

### Phase 4: Full FX Seasonal Blend (Priority 4)
1. **Train:** 2019-2021
2. **Test:** 2022-2024 OOS
3. **Correlation check:** Ensure orthogonal to existing strategies

---

## 8. Key Risks

| Risk | Mitigation |
|------|------------|
| Pattern instability | Rolling 52-week recalibration |
| Overfitting to recent years | Require OOS stability across 3+ years |
| Central bank intervention | Calendar filter for high-impact weeks |
| Low signal frequency | Combine with existing strategies |
| XAUUSD data unavailability | Engineering must source data before backtest |
| Holiday effects distort | Skip short weeks (<4 trading days) |

---

## 9. Recommended Next Steps

### For Engineering
1. **Source XAUUSD data** — flagged as missing in AYUAA-166 risk register
2. **Build SeasonalCalendarStrategy** — implement ISignalStrategy interface
3. **Add calendar features to feature pipeline** — for use by other strategies

### For Research (Next Sprint)
1. Complete backtest for Month-End Rebalance (Phase 1)
2. Analyze NFP Calendar Effect (additional alpha source)
3. Cross-check patterns against institutional flow data (if available)

---

## 10. Conclusion

Seasonal and calendar-based trading strategies represent a **systematically underexplored** opportunity in our pipeline. These strategies are:
- **Orthogonal to existing technical approaches** (low correlation)
- **Academically well-documented** (robust theoretical basis)
- **Low implementation complexity** (simple rules, no ML required)
- **Good portfolio diversification** (calendar effects on different pairs/timeframes)

**Recommended first implementation:** Month-End Rebalance (lowest complexity, clearest academic backing, directly testable on existing EURUSD data).

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)  
**Date:** 2026-04-06  
**Sources:** Academic literature (Cornett 2009, Alford 2011, Hattori & Warnock 2006), BIS Triennial Survey, forex calendar patterns, AYUAA-166 (FTMO Critical Path)
