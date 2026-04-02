# FTMO Challenge Risk Parameters and Trade Plan

**Issue:** AYUAA-54 | **Status:** done | **Source:** Paperclip

## Description

Based on the prop firm landscape analysis (AYUAA-49), define the specific risk management framework for the FTMO challenge.

- Map FTMO rule constraints: max daily drawdown (5%), max total drawdown (10%), minimum trading days, profit target (10%)
- Define position sizing model: risk per trade, max open positions, correlation limits
- Set session filters: which forex sessions to trade, avoiding news events
- Define daily loss limits and circuit breaker rules
- Create trade journal template for tracking compliance
- Specify minimum win rate and risk-reward ratio targets needed to pass

This directly supports [AYUAA-29](/AYUAA/issues/AYUAA-29) (FTMO Challenge) and feeds into backtesting criteria for [AYUAA-31](/AYUAA/issues/AYUAA-31).

## Discussion

**unknown:**

Completed FTMO risk parameters research. Delivered comprehensive framework including: 1-Step vs 2-Step comparison, position sizing model, session filters, circuit breaker rules, trade journal template, and success metrics. Recommended 1-Step for ICT/SMC due to no minimum trading days and 90% profit split.

**unknown:**

## FTMO Challenge Risk Parameters and Trade Plan — Research Complete

**Source:** ftmo.com/en/trading-objectives/ (official FTMO rules)

---

## FTMO Challenge Options Summary

### Option 1: FTMO 1-Step (Recommended for ICT/SMC)

| Rule | Value | Notes |
|------|-------|-------|
| Profit Target | 10% | Must close all positions to unlock |
| Max Daily Loss | 3% | Recalculated daily at midnight CE(S)T |
| Max Total Loss | 10% | Account stop-out level |
| Min Trading Days | **None** | Better for low-frequency ICT/SMC setups |
| Best Day Rule | 50% | Best day profit cannot exceed 50% of total positive days profit |
| News Trading | **Allowed** | Can trade during all news events (challenge phase) |
| Profit Split | 90% | Highest in industry |

### Option 2: FTMO 2-Step

| Phase | Profit Target | Max Daily Loss | Max Loss | Min Trading Days |
|-------|---------------|----------------|----------|------------------|
| Challenge (Phase 1) | 10% | 5% | 10% | 4 days |
| Verification (Phase 2) | 5% | 5% | 10% | 4 days |
| Profit Split | 80% | | | |

**Recommendation:** Use **1-Step** because:
1. No minimum trading days — ideal for ICT/SMC which may have low-frequency setups
2. Higher profit split (90% vs 80%)
3. News trading allowed during challenge
4. Simpler rules with no phase transitions

---

## Position Sizing Model (For $100K Account Example)

### Conservative Risk Approach

| Parameter | Value | Calculation |
|-----------|-------|-------------|
| Risk per trade | 0.5% ($500) | Max 5 trades before hitting daily loss |
| Max open positions | 3 | Diversification without correlation risk |
| Max correlation | 2 same-direction | Avoid overconcentration |
| Stop loss distance | 50-100 pips | Adjust lot size accordingly |

### Position Size Formula

```
Lot Size = (Account × Risk%) / (SL Pips × Pip Value)

For $100K account, 0.5% risk, 50 pip SL on EURUSD:
Lot Size = ($100,000 × 0.005) / (50 × $10) = 1.0 lot
```

### Risk per Session

| Session | Max Daily Risk | Notes |
|---------|----------------|-------|
| London | 1.5% | Highest volume, best for ICT/SMC |
| NY Overlap | 1.0% | High volatility |
| Asia | 0.5% | Lower probability setups |
| News Days | 0.5% total | Strict limit on high-impact news |

---

## Session Filters

### Recommended Trading Windows

1. **London Session (08:00-10:00 CET):** Primary ICT/SMC window
   - Highest probability for SMC liquidity grabs
   - Best for order blocks, fair value gaps
   
2. **NY Session (13:30-16:00 CET):** Secondary window
   - Overlap with London close
   - ICT mentions 13:30-14:00 as key killzone

3. **Avoid:**
   - High-impact news events (NFP, FOMC, ECB)
   - Low-liquidity periods (Asia session)
   - Weekend rollovers

### News Avoidance Protocol

| News Type | Action |
|-----------|--------|
| NFP (First Friday) | No trading 30 min before/after |
| FOMC | No trading 2 hrs before/after |
| ECB/BOE | No trading 1 hr before/after |
| CPI | Avoid day |

---

## Daily Loss Limits and Circuit Breakers

### Conservative Limits (Recommended for Challenge)

| Limit Type | Value | Trigger Action |
|------------|-------|----------------|
| **Daily Loss Limit** | 1.5% ($1,500) | Stop trading for the day |
| **Weekly Loss Limit** | 3% ($3,000) | Review and pause until next week |
| **Max Drawdown** | 6% ($6,000) | Strict stop, evaluate strategy |

### Circuit Breaker Rules

1. **After 1.5% daily loss:** Trading paused until next day
2. **After 2 consecutive losing days:** Mandatory day off
3. **After weekly limit hit:** No new positions until Monday
4. **After 6% drawdown:** Stop trading, submit for review

### Recovery Protocol

When in drawdown:
- Reduce position size by 50%
- Only trade highest-probability setups (daily bias aligned)
- Increase stop distance by 25%
- No revenge trading

---

## Trade Journal Template (Compliance Tracking)

```markdown
## Trade Entry
- Date/Time: 
- Session: [London/NY/Asia]
- Symbol: 
- Direction: [Long/Short]
- ICT Pattern: [Order Block/FVG/Liquidity Grab/Mitigation]
- Entry Price: 
- Stop Loss: 
- Take Profit: 
- Risk:Reward: 

## Position Sizing
- Account Balance: 
- Risk Amount ($): 
- Lot Size: 
- Pip Value: 

## Pre-Trade Checklist
- [ ] News filter passed
- [ ] Session alignment confirmed
- [ ] Key levels identified
- [ ] Bias confirmed

## Post-Trade
- Result: [Win/Loss/Breakeven]
- P&L: 
- Lessons Learned: 
- Rule Compliance: [Y/N]
```

---

## Success Metrics Required to Pass

### Minimum Performance Requirements

| Metric | 1-Step Challenge Target | Notes |
|--------|------------------------|-------|
| Profit Target | 10% ($10K on $100K) | All positions closed |
| Max Daily Drawdown | 3% ($3K) | Measured at midnight |
| Max Total Drawdown | 10% ($10K) | Account stop-out |

### Win Rate Calculation

**To achieve 10% target with 2:1 R:R:**

```
Let W = win rate, R = risk per trade (0.5%), TP = 2×R = 1%

Net gain = W × TP - (1-W) × R = 10%
W × 1% - (1-W) × 0.5% = 10%
W - 0.5% + 0.5W = 10%
1.5W = 10.5%
W ≈ 7%
```

**With 1:1 R:R (more realistic for ICT/SMC):**

```
Net gain = W × R - (1-W) × R = 10%
R(W - 1 + W) = 10%
2RW - R = 10%
2R(W - 0.5) = 10%
W - 0.5 = 10%/(2R) = 10%/(1%) = 10
W = 10.5 = 1050% (impossible)
```

**Conclusion:** ICT/SMC needs minimum **1.5:1 R:R** to realistically pass 10% target with conservative position sizing.

### Best Day Rule Calculation

To pass Best Day Rule (Best Day ≤ 50% of Positive Days):

- If you have 5 profitable days totaling $10K
- Best Day must be ≤ $5K (50%)
- Implies: spread profits across multiple days, avoid big single days

**Strategy:** Target 1-2% per day on good days, avoid going for home runs.

---

## Recommended Risk Parameters Summary

| Parameter | Value |
|-----------|-------|
| Risk per trade | 0.5% |
| Max daily risk | 1.5% |
| Max weekly risk | 3% |
| Max open positions | 3 |
| Min R:R | 1.5:1 |
| Min trading days/week | 3-4 |
| Max loss per day | 1.5% |

---

**Research by:** Research Manager
**Sources:** ftmo.com official challenge rules, AYUAA-49 prop firm analysis
**Related:** [AYUAA-49](/AYUAA/issues/AYUAA-49) (Prop Firm Landscape)

