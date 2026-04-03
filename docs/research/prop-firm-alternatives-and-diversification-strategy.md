# Prop Firm Alternatives and Diversification Strategy

**Issue:** [AYUAA-107](/AYUAA/issues/AYUAA-107) | **Status:** done

## Context

Our forex path targets FTMO challenge ([AYUAA-29](/AYUAA/issues/AYUAA-29)), but backtests returned NO-GO and strategy iteration is underway. Having backup options is prudent. This document evaluates non-FTMO prop firms as alternatives or supplementary options.

## Prop Firms Evaluated

| Firm | Status | Focus | cTrader | Forex |
|------|--------|-------|---------|-------|
| **The 5%ers** | Active (since 2016) | CFDs/Forex | Yes | Yes |
| **E8 Markets** | Active (since 2021) | Forex/Futures/Crypto | Yes (via E8 Funding) | Yes |
| **FundedNext** | Active | CFDs/Futures | Via Match-Trader | Yes |
| **Topstep** | Active | Futures ONLY | No | **No** |
| **MyForexFunds** | Returning (2026) | Forex | Unknown | Yes |

---

## The 5%ers — Detailed Analysis

### Overview
- **Founded:** 2016, 10+ years in business
- **Scale:** 262K funded traders, $149M+ paid out, 149 employees in 23 countries
- **Reputation:** 4.7/5 Trustpilot, multiple industry awards
- **Sister brands:** TradeThePool (stocks), Tradedelicious, TSG Brokers

### Challenge Structure

| Program | Steps | Profit Target | Daily Loss | Max Loss | Profit Split |
|---------|-------|---------------|------------|----------|--------------|
| **Hyper Growth (1-Step)** | 1 | 10% | 3% | 6% stop-out | Up to 100% |
| **High Stakes (2-Step)** | 2 | 10% / 10% | 3% | 6% stop-out | Up to 100% |
| **Bootcamp (3-Step)** | 3 | Lower per phase | 4% | 8% | Up to 100% |

### Account Sizes & Fees

| Account | Fee (USD) | Fee (EUR) | Fee (GBP) |
|---------|-----------|-----------|-----------|
| $5K | $74 | €69 | £59 |
| $10K | $137 | €129 | £109 |
| $20K | $257 | €239 | £209 |

### Key Advantages for Our Use Case
1. **cTrader native support** — matches our existing infrastructure
2. **No time limits** on any program
3. **100% profit split** available (highest in industry)
4. **Low minimum ($74 for 5K)** — affordable entry
5. **Scaling to $4M** — highest max account in industry
6. **10 years in business** — proven reliability

### Concerns
- 3 minimum profitable days required (Hyper Growth)
- Stop-out level at 6% is tighter than FTMO's 10% max loss
- Higher leverage (1:30) vs FTMO (1:100)

---

## E8 Markets — Detailed Analysis

### Overview
- **Founded:** 2021, $63M+ paid to traders
- **Scale:** Strong community, Discord active
- **Reputation:** Positive reviews, 4.5/5 Trustpilot
- **Legal entities:** E8 Funding LLC (US/Dallas), E8 Markets Ltd (St. Lucia)

### Challenge Structure

| Program | Profit Target | Daily Loss | Max Loss | Profit Split |
|---------|---------------|------------|----------|--------------|
| **E8 One** | 8% | 5% | 10% | Up to 90% |
| **E8 Futures** | Varies | 5% | 10% | Up to 90% |
| **E8 Crypto** | Varies | 5% | 10% | Up to 90% |

### Key Advantages
1. **cTrader support** via E8 Funding
2. **No time limits**
3. **Fast payouts** — "payouts in 3 days" claimed
4. **Multiple markets** — Forex, Futures, Crypto (single account)
5. **Low fees** starting competitive

### Concerns
- Simulated trading environment (like all prop firms)
- Relatively newer company (3 years vs 10+ for established players)
- Some withdrawal limits by jurisdiction

---

## FundedNext — Additional Notes

From prior analysis (AYUAA-49):
- **Founded:** Growing fast, 125K+ accounts
- **Profit splits:** Up to 95% (highest available)
- **Challenge fees:** ~$530 for 100K
- **cTrader:** Via Match-Trader platform
- **Payout:** 24hr guarantee
- **Scaling:** Up to $300K

### Concerns
- Match-Trader (not native cTrader)
- Less established than FTMO/5%ers

---

## Topstep — Futures Only (NOT Forex)

**Important:** Topstep is futures-only (CME, COMEX, NYMEX, CBOT). No forex, no CFDs. Cannot be used as FTMO alternative for our forex strategy.

---

## MyForexFunds — Returning in 2026

From their site (March 2026):
- US case victory (dismissal of all allegations)
- Receivership unwound
- Support channels reopening
- Platform being re-established

### Caution
- Was popular but shut down in 2023 due to legal issues
- Re-opening is recent — track record starts fresh
- Recommend waiting for established track record before using

---

## Comparison Matrix

| Criteria | FTMO | The 5%ers | E8 Markets | FundedNext |
|----------|------|-----------|------------|------------|
| **Min Account** | $10K | $5K | ~$10K | $6K |
| **Challenge Fee (10K)** | ~$300 | $137 | ~$200 | ~$150 |
| **Profit Target** | 10% | 10% | 8% | 8% |
| **Daily Loss** | 5% | 3% | 5% | 5% |
| **Max Loss** | 10% | 6% stop-out | 10% | 10% |
| **Profit Split** | 90% | 100% | 90% | 95% |
| **Time Limit** | None (1-Step) | None | None | 30 days |
| **cTrader** | Yes | Yes | Yes | Match-Trader |
| **Scaling** | $200K | $4M | $1M | $300K |
| **Years Active** | 10+ | 10+ | 3 | 3 |
| **Payout Reliability** | Excellent | Excellent | Good | Good |

---

## Recommendations

### Primary Alternative: **The 5%ers**

**Rationale:**
1. **cTrader support** — matches our existing cAlgo/cTrader infrastructure
2. **100% profit split** — best in industry (vs 90% at FTMO)
3. **Lower cost entry** — $74 for 5K (vs ~$300 for FTMO 10K)
4. **Scaling to $4M** — 20x FTMO's max
5. **10+ years proven** — comparable to FTMO reliability
6. **Tighter daily loss (3%)** — actually better risk management

**Concern mitigated:** Stop-out at 6% is tighter than FTMO's 10% max loss, but 3% daily loss limit is same as FTMO 1-Step.

### Secondary Alternative: **E8 Markets**

**Rationale:**
1. cTrader available
2. Fast payout claims (3 days)
3. Multi-market (useful if we expand to futures/crypto later)
4. Lower challenge targets (8% vs 10%)

### Third Option: **FundedNext** (if cTrader flexibility acceptable)

**Rationale:**
1. 95% profit split
2. $6K minimum (lowest entry point)
3. 24hr payout guarantee

**Concern:** Uses Match-Trader, not native cTrader.

---

## Diversification Strategy

Given our $150 capital constraint:

1. **Start with The 5%ers 5K ($74)** — lowest risk entry with real infrastructure
2. **If successful, scale with The 5%ers** — can reach $4M (vs FTMO's $200K)
3. **Parallel run E8 Markets** — test second platform without full commitment
4. **Monitor MyForexFunds** — may become viable later in 2026 once track record builds

### Fee Analysis on $150 Capital

| Firm | Smallest Challenge | Fee | % of Capital |
|------|-------------------|-----|--------------|
| The 5%ers 5K | $5,000 | $74 | 49% |
| E8 Markets | ~$10K | ~$200 | 133% |
| FundedNext 6K | $6,000 | ~$150 | 100% |
| FTMO 10K | $10,000 | ~$300 | 200% |

**The 5%ers 5K is the only option where fees don't exceed our capital.**

---

## cTrader Compatibility Assessment

| Firm | Platform | cTrader Direct | Notes |
|------|----------|---------------|-------|
| **FTMO** | cTrader, MT4, MT5 | Yes | Native cTrader |
| **The 5%ers** | cTrader, MT4, MT5 | Yes | Native cTrader |
| **E8 Funding** | cTrader, Tradelocker | Yes | Native cTrader |
| **E8 Markets** | MT5 | No | MT5 only |
| **FundedNext** | Match-Trader | No | Not cTrader |

---

## Summary Recommendations

1. **Primary backup to FTMO:** **The 5%ers** — best combination of low cost entry, cTrader support, 100% splits, and 10-year track record
2. **If The 5%ers unavailable or fails:** **E8 Markets** or **FundedNext**
3. **Avoid:** Topstep (futures only), MyForexFunds (wait for track record to build)
4. **For $150 capital:** The 5%ers 5K challenge ($74) is the only viable path that doesn't require investing more than capital in fees

---

## Next Steps

- Kai to evaluate The 5%ers cTrader connectivity for ICT/SMC strategy compatibility
- Consider running parallel demo accounts on The 5%ers while FTMO strategy iteration continues
- Monitor MyForexFunds re-launch stability before considering

---

**Sources:** the5ers.com, e8markets.com, fundednext.io, topstep.com, myforexFunds.com, AYUAA-49 prior analysis
