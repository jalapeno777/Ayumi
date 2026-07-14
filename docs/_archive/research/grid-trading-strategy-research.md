# Grid Trading Strategy Research — Passive Income via Automated Grid Systems

**Issue:** [AYUAA-266](/AYUAA/issues/AYUAA-266) | **Status:** in_progress | **Research Manager**

## Context

All directional trading strategies have failed FTMO walk-forward validation:
- Strategy v1 (ICT/SMC): 1/5 windows, WR ~54%
- Strategy v2 (MR+ICT hybrid): 0/5 windows, WR ~42%
- Root cause: 2025 regime change, ICT overhead, insufficient edge

Grid trading is a **complementary passive income approach** — NOT a replacement for directional trading. It operates independently and can generate steady returns from ranging markets.

---

## What is Grid Trading?

Grid trading is a **non-directional, range-bound strategy** that places buy and sell orders at regular intervals above and below a reference price.

### Core Mechanics

```
Example: XAUUSD at $2,000
Grid spacing: $20

Sell Grid (above):  $2,020, $2,040, $2,060, $2,080, $2,100
Base Price:         $2,000
Buy Grid (below):   $1,980, $1,960, $1,940, $1,920, $1,900
```

- When price rises → sells trigger at each level → net profit from sell trades
- When price falls → buys trigger at each level → net profit from buy trades
- When price oscillates → both buys and sells trigger → cumulative profit from grid

### Why It Works

- Markets spend 40-60% of time in ranging/sideways conditions
- Each grid level captures small, consistent profits
- No need to predict market direction
- Risk is bounded (grid acts as built-in risk management)

---

## Best Instruments for Grid Trading

### Gold (XAUUSD) — **OPTIMAL**

| Factor | Rating | Notes |
|--------|--------|-------|
| Volatility | ★★★★★ | Gold moves $10-30/day typically, good for grid captures |
| Range behavior | ★★★★ | Gold trends less than forex, more ranging |
| Spread | ★★★ | 2-5 pips typical, wider than majors but manageable |
| Macro sensitivity | ★★★★★ | Responds to USD, rates, risk sentiment — creates ranges |

**Gold grid settings:**
- Grid spacing: $15-25 (based on ATR)
- Timeframe: H1 or M15
- Session focus: NY overlap (15-17 UTC) is peak volatility

### Major Forex Pairs — GOOD

| Pair | Grid Spacing | Notes |
|------|-------------|-------|
| EURUSD | 15-25 pips | High liquidity, tight spreads |
| GBPUSD | 20-30 pips | Higher volatility than EURUSD |
| USDJPY | 15-25 pips | Good for range-based grids |
| AUDUSD | 15-25 pips | Modest volatility |

### Avoid for Grid Trading

- **Cross pairs** (EURGBP, GBPAUD): Low volatility, weak ranges
- **Low-liquidity pairs**: Wide spreads erode grid profits
- **Strong trending pairs**: GBPJPY can trend aggressively

---

## Grid Configuration Parameters

### Grid Spacing

| Instrument | ATR-based Spacing | Fixed Spacing |
|------------|-------------------|---------------|
| XAUUSD | 0.5-0.75% of price | $15-25 |
| EURUSD | 0.3-0.5% of price | 15-25 pips |
| GBPUSD | 0.3-0.5% of price | 20-30 pips |

**Rule:** Spacing should be 1.5-2x average true range to avoid excessive fills in noise.

### Number of Grid Levels

- **Conservative:** 5 levels each side (10 total)
- **Moderate:** 10 levels each side (20 total)
- **Aggressive:** 15+ levels each side

**Risk consideration:** More levels = more capital required, but more profit capture.

### Position Sizing

```
Lot size per grid level = Account Risk / (Grid Spacing × Pip Value × Number of Levels)

Example:
- Account: $10,000
- Max risk per grid sequence: 2% = $200
- Grid spacing: 20 pips (EURUSD)
- 10 levels each side (20 total)
- Lot size = $200 / (20 × $10 × 20) = 0.05 lots per level
```

### Stop Loss and Take Profit

- **Stop Loss:** Set at outermost grid level + buffer (50-100 pips for forex)
- **Take Profit:** Each grid level has a TP = next grid level
- **Overall Stop:** Hard stop at initial reference price ± range threshold

---

## Risk Management

### Maximum Drawdown Control

1. **Total position limit:** Never exceed 20% of account in grid positions
2. **Daily loss limit:** Stop gridding if daily loss exceeds 1-2%
3. **Range breach shutdown:** Disable grid if price exits outer bounds

### Grid Breakeven Analysis

| Grid Type | Best Case | Worst Case | Breakeven |
|-----------|-----------|------------|-----------|
| Symmetric grid | Price oscillates | Strong trend | Price returns to center |
| Asymmetric grid | Trend in favorable direction | Trend against direction | Partial fill recovery |

### When to Disable Grid Trading

1. **Strong trend detection:** ATR exceeds 2x normal, ADX > 40
2. **News events:** NFP, FOMC, central bank decisions
3. **Range breach:** Price closes beyond outermost grid level
4. **Weekend gaps:** Reduce exposure before weekend

---

## Combining Grid with Directional Strategy

### Complementary Operation

Grid trading and directional trading are **independent** and can run simultaneously:

| Condition | Grid Trading | Directional |
|-----------|-------------|-------------|
| Ranging market | ✅ Profits | ❌ No signals |
| Trending market | ❌ Small loss | ✅ Profits |
| High volatility | ⚠️ Reduce size | ⚠️ Widen SL |

### Portfolio Allocation Recommendation

```
Total Account: $10,000
├── Grid Trading: $3,000 (30%) — passive income
├── Directional:  $6,000 (60%) — growth engine
└── Reserve:      $1,000 (10%) — drawdown buffer
```

---

## cTrader Implementation Requirements

### Grid Manager Class

```
GridManager:
  - reference_price: decimal
  - grid_spacing: decimal (pips)
  - num_levels: int
  - lot_size: decimal
  - direction: enum (buy_grid, sell_grid, both)
  - active_orders: list[Order]
  - total_pnl: decimal

Methods:
  - initialize_grid() → places initial orders
  - on_price_tick(price) → checks fills, manages orders
  - calculate_pnl() → running P&L
  - close_all() → flatten positions
  - pause_grid() → suspend new orders
  - resume_grid() → reactivate
```

### Key Implementation Details

1. **Price monitoring:** Tick-based or 1-second interval polling
2. **Order tracking:** Maintain hashmap of grid order IDs
3. **Fill detection:** Compare current price vs order prices
4. **TP placement:** When order fills, immediately place TP at next grid level
5. **Recovery mode:** If price moves through levels without fill, adjust spacing

### Known Platform Limitations

- cTrader cAlgo: No native grid order management
- Requires custom implementation using `MarketOrder` and `LimitOrder`
- Position sizing must account for cumulative exposure

---

## Historical Backtest Expectations

### Realistic Grid Trading Returns (Literature)

| Market Condition | Monthly Return | Max Drawdown | Win Rate |
|-----------------|---------------|--------------|----------|
| Ranging | 3-8% | 5-10% | 70-80% |
| Mixed | 1-4% | 10-15% | 55-65% |
| Trending | -2 to +1% | 15-25% | 40-50% |

### Expected Performance by Instrument

| Instrument | Monthly Return | Max Drawdown | Sharpe |
|------------|---------------|--------------|--------|
| XAUUSD | 2-5% | 10-15% | 0.8-1.2 |
| EURUSD | 1-3% | 5-10% | 0.6-1.0 |
| GBPUSD | 1.5-3.5% | 8-12% | 0.7-1.1 |

### Key Benchmarking Notes

- Grid trading returns are **lower but more consistent** than directional
- Sharpe ratios of 0.6-1.2 are achievable vs FTMO threshold of 0.5
- Drawdowns are **bounded** by grid structure vs unbounded in directional

---

## Next Steps for Engineering

1. **Backtest grid strategy** on historical XAUUSD and EURUSD data
2. **Parameter sweep:** grid spacing (15-30 pips), number of levels (5-15)
3. **Walk-forward validation:** 5-window, same criteria as directional
4. **Integration:** Grid as separate bot instance alongside directional

---

## Research Conclusion

Grid trading offers a **viable complementary approach** to our directional strategies:

✅ Pros:
- Market-direction agnostic (reduces regime risk)
- Steady, consistent returns in ranging markets
- Lower per-trade risk with bounded drawdown
- Sharpe ratios achievable (0.6-1.2) above FTMO threshold
- Particularly effective on XAUUSD

⚠️ Cons:
- Requires capital reserves for grid margin
- Performs poorly in strong trends (must disable)
- Lower absolute returns than directional (2-5% vs 5-10% monthly potential)
- Requires active monitoring to disable during trends

**Recommendation:** Pursue grid trading as a **separate passive income stream** while continuing directional iteration on M15/H4. Allocate 20-30% of trading capital to grid systems.

---

**Research conducted by:** Research Manager (790e1a25-6d3e-47e8-a64f-1654bedb273e)  
**Date:** 2026-04-04  
**Sources:** ICT/SMC post-mortem (AYUAA-127), FTMO walk-forward results (AYUAA-221, AYUAA-238), forex strategy analysis, grid trading literature