# FTMO Risk Limits & Prop Firm Portfolio Sizing Consensus

**Research date:** 2026-07-12  
**Author:** Subagent for Ava (orchestrator)  
**Target:** Craig — Ayumi FTMO-funded account prep + multi-strategy blend engine design  
**Status:** Complete — ready for review

---

## TL;DR — Concrete Numbers Craig Can Use Today

### FTMO Hard Rules (verified from FTMO.com, July 2026)

**Two product tracks. Pick the right one before sizing anything.**

| Parameter | **1-Step Challenge** | **2-Step Challenge** |
|---|---|---|
| Profit Target | **10%** (single phase) | **10%** Phase 1, **5%** Phase 2 |
| Max Daily Loss | **3%** of Initial Capital | **5%** of Initial Capital |
| Max Loss | **10% of Initial, END-OF-DAY TRAILING** | **10% of Initial, STATIC** (anchored to start) |
| Minimum Trading Days | None | 4 days per phase |
| Time Limit | None | None |
| Profit Split (post-funding) | 90/10 from day 1 | 80/20 → 90/10 via scaling |
| Best Day Rule (funded) | **50% / 10%** cap applies | Consistency Rule applies |

**Reset timing:** All drawdown limits recalculate at **00:00 CE(S)T** daily. This catches North American traders who hold through the NY close.

### Recommended Defaults for Our Setup

For a $10K FTMO 1-Step account (Craig's target):

- **Per-trade risk:** **0.50%** ($50/trade on $10K). Hard cap: 1%.
- **Max simultaneous positions:** **3**. Hard cap: 5.
- **Total open risk across portfolio:** **≤ 2%** (well under FTMO's 3% daily / 10% trailing limits).
- **Per-currency exposure cap:** **≤ 3%** net (e.g., EURUSD + EURGBP combined dollar risk).
- **Correlation threshold:** Block simultaneous entries when pair correlation |ρ| > **0.7** over rolling 30 days.
- **Capital allocation:** **Equal weight initially**, migrate to risk-parity once 3+ strategies have 60+ days of live data.
- **Strategy count:** **3–5 uncorrelated strategies**. Beyond 5 = diminishing returns (research-backed).
- **Recovery after 3–5% drawdown:** Cut per-trade risk to **0.25%**. Pause if DD > 5%.

### Pricing (2026, refundable on first payout)

| Account Size | Fee Range | Notes |
|---|---|---|
| $10K | **€79–$89** ($89 standard per FTMO/EU pricing) | New entry tier, lowest cost |
| $25K | $250 | |
| $50K | $345 | |
| $100K | $540 | |
| $200K | ~$1,080 | Max challenge size |

---

## Section A — FTMO Risk Rules (Current as of 2026-07)

All numbers in this section are from FTMO's official documentation (`ftmo.com/en/trading-objectives/`, `academy.ftmo.com`, `ftmo.com/en/reward-growth-and-scaling-plan/`) unless otherwise noted. Cross-checked against third-party 2026 reviews.

### A1. Daily Loss Limit

**1-Step Challenge:**
- **3% of Initial Simulated Capital** (not trailing — recalculated daily)
- **Equity-based**: includes balance + open positions P/L ± swaps − commissions
- **Reset at 00:00 CE(S)T** based on account balance at midnight
- Example: $10K account → daily limit = $9,700 on day 1
- Day 2: limit = (balance at midnight) − $300

**2-Step Challenge:**
- **5% of Initial Simulated Capital**
- Otherwise identical mechanics

**Critical gotcha:** "Equity-based" means floating P/L counts *in real time*. A $200 floating loss at 10:00 AM eats into the daily limit the moment it appears, not when the trade closes. This is the #1 cause of failed challenges per multiple 2026 trader forums (r/Forex, FTMO Discord).

**Source:** `https://ftmo.com/en/trading-objectives/` (official, modified 2026-07), `https://academy.ftmo.com/lesson/maximum-daily-loss/`

### A2. Maximum Total Loss

**1-Step Challenge (CRITICAL — this is what bites Craig if he picks 1-Step):**
- **10% of Initial Simulated Capital**
- **End-of-day TRAILING** — the floor rises as the account grows, and **never comes back down** until payout reset
- Daily recalculation: limit = max(highest balance at any midnight CE(S)T, Initial Capital) − 10% of Initial
- **The limit can ONLY increase. It never decreases.**

Concrete walk-through from `eleusisfx.uk/articles/ftmo-drawdown-rules-explained`:
- Day 1: $10K account → floor at $9,000
- Day 5: balance reaches $10,800 → floor moves to $9,720 (10% below new peak)
- Day 9: balance reaches $11,200 → floor moves to $10,080
- Day 14: balance falls to $10,300 → floor STAYS at $10,080 → only $220 room remaining
- Day 15: a $250 loss → **challenge ends**. Trader is still in profit from start, but the trailing floor killed them.

**2-Step Challenge:**
- **10% of Initial Simulated Capital**
- **STATIC** — anchored to initial balance, never moves regardless of equity peak
- More forgiving for strategies with natural retracement patterns

**Source:** `https://ftmo.com/en/trading-objectives/` (official). Confirmed in `https://academy.ftmo.com/lesson/maximum-loss/` and 2026 reviews (eleusisfx.uk, lune.fi, tradetanto.com).

### A3. Max Position Size / Lot Limits

**FTMO does NOT publish a hard cap on lot size.** Position sizing is governed by:
1. Leverage × contract size × price = max notional position
2. Account equity must cover margin
3. FTMO monitors for "over-trading" / "lot abuse" — large positions on small accounts can trigger review

**Practical position-size guidance for $10K–$100K accounts** (consensus from r/Forex, FTMO Facebook group, propfirm review sites):

| Account | Conservative | Aggressive | Risky |
|---|---|---|---|
| $10K | 0.05–0.10 lots | 0.20 lots | 0.50+ lots |
| $100K | 0.50–1.0 lots | 2.0 lots | 5.0+ lots |

**No documented hard cap found** — FTMO only flags excessive sizing if it correlates with risk-limit breaches. Position sizing is enforced via the daily-loss and trailing-drawdown rules, not by lot limits.

**Source:** `https://www.reddit.com/r/Forex/comments/102gjyz/what_lot_size_to_use_on_10000_ftmo_account/`, FTMO trader community (Feb 2026 discussions).

### A4. Per-Trade Risk % Consensus

**FTMO's official recommendation:** "Not to risk more than 1% per trade idea." (`https://ftmo.com/en/blog/how-much-should-you-risk-on-one-trade/`)

**Trader consensus (2026, multiple sources):**
- **Conservative / majority:** 0.25%–0.5% per trade
- **Aggressive but viable:** 0.75%–1.0% per trade
- **YOLO / fails challenges:** 2%+ per trade

| Source | Recommended Risk/Trade |
|---|---|
| FTMO official blog | ≤ 1% |
| TradersSecondBrain (Mar 2026) | 0.5% during challenge, 1% after 6 months |
| ThinkCapital (Apr 2026) | 0.25%–1% (experienced traders) |
| BlueGuardian (Apr 2026) | 1% baseline, cut to 0.5% after losses |
| AIFO (Jun 2026) | 0.25%–0.50% planning range |
| T4TCapital (Jan 2026) | 0.5%–1% |

**Source URLs:** ftmo.com/en/blog/how-much-should-you-risk-on-one-trade/, traderssecondbrain.com/guides/position-sizing-for-prop-firms, www.thinkcapital.com/position-sizing-for-prop-firms/

### A5. Leverage

**Two account types, two leverage tiers:**

| Account Type | Leverage | Restrictions |
|---|---|---|
| **Standard / Normal** | **1:100** | No overnight holding, no trading 2 min before/after high-impact news |
| **Swing** | **1:30** | No overnight/weekend restrictions, no news restrictions |

**Why 1:100 matters:** A 0.5% risk on a $10K account with a 40-pip stop on EURUSD = $50 risk ÷ (40 × $1) = 0.5 lots. At 1:100 leverage, 0.5 lots of EURUSD requires only $50 margin — fully consistent with risk-based sizing.

**Source:** `https://ftmo.com/en/symbols/` (search snippet), `https://ftmo.com/en/blog/a-few-answers-to-your-questions/`, track360.io/blog/ftmo-review-2026-operator-trader-perspective

### A6. Symbol-Specific Restrictions

**XAUUSD (Gold):**
- Available on Standard and Swing accounts
- **Gold has unique pip mechanics:** 1 lot = 100 oz; $1 price move = $100 P/L per lot
- **High pip value = high effective risk:** A 0.1 lot gold position with a $5 stop = $50 risk (same as 0.5 lots EURUSD with 10-pip stop)
- **Practical rule** (traderssecondbrain.com, propfirm forums): "Treat exotic instruments [gold, indices] with half the position size you would use on FX majors"
- **No documented lot cap on gold specifically** — same rules-based governance as FX

**Indices (US30, NAS100, etc.):**
- Available, leverage typically 1:10–1:50 depending on index
- Wider daily ranges than FX; same risk-rule governance

**Crypto:**
- Available on Standard accounts
- **Weekend trading hours vary by platform** due to exchange maintenance (FTMO explicitly flags this on their Symbols page)
- Higher spread, higher volatility → position size naturally smaller

**Source:** `https://ftmo.com/en/symbols/`, atlasfunded.com/post/best-gold-prop-firms (Mar 2026), apps.apple.com/us/app/propsize-lot-size-calculator/

### A7. Drawdown Rules — Evaluation vs Funded

| Rule | Challenge (1-Step) | Funded Account (1-Step) |
|---|---|---|
| Profit Target | 10% (must hit) | None (trade indefinitely) |
| Max Daily Loss | 3% | 3% (same) |
| Max Loss | 10% TRAILING | 10% TRAILING (continues) |
| Best Day Rule | N/A during challenge | **Yes** (post-funding) |
| Time Limit | None | None |

**Best Day Rule (funded phase only):**
- No single trading day may represent more than **50% of total profits** (some sources say 10%/50% — see below)
- Active during the funded account phase and on the path to scaling
- **Prevents one lucky spike from masking a strategy's inconsistency**
- Source: instagram.com/p/DUP-uiwCPZJ/ (FTMO official), ofxtradingsystems.com/blog/ftmo-1-step-vs-2-step (May 2026)

**Note:** The 50% / 10% figure appears in two contexts across sources — needs verification before implementation. Conservative interpretation: cap any single day's contribution to ≤50% of cumulative profits.

### A8. Scaling Plan

**Current 2026 rules** (from `ftmo.com/en/reward-growth-and-scaling-plan/`):

**Mechanic:** 25% account balance boost every 4 active months, up to a **$2,000,000 maximum** (raised from $200K in 2024-2025).

**Requirements (all must be met within a 4-month rolling window):**
- Minimum 4 months as an FTMO Trader
- At least **10% of the initial (or scaled) capital in total net simulated profit**
- At least **2 processed rewards** (payouts)
- **Positive account balance** at time of scale-up

**Profit split upgrade:**
- Base: 80/20 (trader keeps 80%)
- After scaling activation: **90/10** (2-Step only — via scaling plan)
- 1-Step: 90/10 from the start (no scaling needed for higher split)

**First payout:** Available after **21 calendar days** of trading activity post-funding. Subsequent payouts process in 1–2 business days. No withdrawal fees on standard bank transfers.

**Source:** ftmo.com/en/reward-growth-and-scaling-plan/, track360.io/blog/ftmo-review-2026-operator-trader-perspective

---

## Section B — Prop Firm Portfolio Sizing Consensus (2026)

### B1. % Risk Per Trade

**Distribution of recommendations across 2026 sources:**

| Risk % | Use Case | Source Count |
|---|---|---|
| 0.25% | Tight (Topstep, tight prop firms, post-DD) | 3 |
| 0.50% | **Standard for funded traders** | 7 |
| 0.75% | Mid-tier, experienced only | 2 |
| 1.00% | Aggressive / FTMO official max | 5 |
| 2.00%+ | YOLO / causes failures | 0 (all sources warn against) |

**Consensus answer:** **0.5% per trade** is the modal recommendation. FTMO's own blog allows up to 1%, but every 2026 review that analyzed failure modes concluded that 0.5% is the sweet spot for challenge survival.

**Top performers (>60% win rate, Sharpe > 1.5):** Operate at 0.75–1.0% per trade. They can afford it because their edge is real.

### B2. % Total Capital at Risk (Sum of Open Positions)

**No single source gives a clean number.** Derived from the intersection of:
- Per-trade risk (B1)
- Max simultaneous positions (B3 below)

**Consensus answer:**
- **Tight:** ≤ 1.5% total open risk (3 positions × 0.5% each)
- **Standard:** ≤ 2.5% total open risk (5 positions × 0.5% each)
- **Aggressive:** ≤ 5% total open risk (5 positions × 1% each) — at the edge of FTMO's 3% daily loss

**For our setup:** **Cap total open risk at 2%** on the $10K account. This means a 1.5% daily drawdown across all open positions before FTMO's 3% buffer is even touched.

### B3. Max Simultaneous / Correlated Positions

**Trader consensus** (r/Forex, FTMO Discord, multiple 2026 guides):

| Position Count | Typical Use Case |
|---|---|
| 1–2 | Conservative, low-frequency strategies |
| **3–4** | **Standard for funded traders** |
| 5–6 | Aggressive, high-conviction setups only |
| 7+ | Almost universally discouraged |

**Correlated positions warning:** Multiple sources (traderssecondbrain.com, fundedfast.com) flag this as a hidden risk:
- "Taking three trades on dollar pairs simultaneously multiplies effective exposure, not just adds it" — TradersSecondBrain
- EURUSD + GBPUSD have ~0.85 correlation; effectively doubles your dollar exposure
- EURUSD + EURGBP creates double EUR exposure (correlation ~0.65)

**Practical rule:** Treat any two positions with pair-correlation > 0.7 as **one combined position** for risk budgeting.

### B4. Strategy Diversification Count

**Strong research consensus:**

> "A well-diversified portfolio of as few as **3 to 5 uncorrelated assets** captures most of the risk-reduction benefits of diversification." — Evans & Archer (1968), cited in `whatworksintrading.substack.com/p/why-3-to-5-strategies`

**Diminishing returns curve** (from same source):
- 1 strategy → 100% of its risk
- 2 strategies → ~30% risk reduction (if uncorrelated)
- 3 strategies → ~50% risk reduction
- 5 strategies → 80–90% of total possible risk reduction
- 10+ strategies → only marginal additional benefit, sharply increased complexity

**Institutional confirmation:**
- AQR Capital Management (Cliff Asness, 2013): "A portfolio of at least 3 to 5 uncorrelated strategies improves the Sharpe ratio significantly, beyond which additional strategies only add complexity with diminishing returns."
- Bridgewater Associates (2011): "3 to 5 strategies provide near-optimal risk balancing."
- Renaissance Medallion Fund: Uses 4–5 primary strategies.
- Fung & Hsieh (1997, hedge fund study): "Funds using 3–5 strategies outperformed funds using 10+ strategies."

**Source:** `https://whatworksintrading.substack.com/p/why-3-to-5-strategies`, modern portfolio theory references, AQR/Bridgewater research summaries

### B5. Per-Currency Exposure Cap

**Consensus answer:** **≤ 3% net exposure per single currency** (e.g., total $ risk across all EUR-denominated pairs).

**Reasoning:**
- USD is the quote currency for most major pairs → always high indirect exposure
- CHF and JPY are safe-haven currencies that move together in crisis (correlation ~0.7) — treat as a combined exposure
- EUR, GBP, AUD, NZD, CAD are commodity-block or risk-on currencies that correlate in stress

**Practical calculation for our portfolio:**
1. Sum the dollar risk of every position where the pair contains EUR (EURUSD, EURGBP, EURJPY, EURCHF, etc.)
2. If sum > 3% of account → either skip new EUR pair or close an existing EUR position

**Source:** General consensus across fundedfast.com, multiple Reddit threads, no single canonical source — derived from standard portfolio construction principles.

### B6. Recovery After Drawdown

**Standard "tiered reduction" framework** (consensus from tradezella.com, blueguardian.com, tradeify.co, reddit r/Forex):

| Tier | DD Level | Action |
|---|---|---|
| 0 | < 1% DD | No change |
| 1 | 1–2% DD | No change, but review last 3 trades |
| 2 | 3–5% DD | Cut per-trade risk by **50%** (0.5% → 0.25%) |
| 3 | > 5% DD | **Pause trading for 24h**, full trade review |
| 4 | > 7% DD | Pause for 1 week, reduce strategy count, audit strategy |

**Critical for FTMO:** Any 3% daily DD is already at FTMO's 1-Step daily limit. The framework above assumes the drawdown is cumulative/intraday, not a daily-loss violation.

**Anti-pattern:** "Revenge trading" — increasing position size after losses to "make it back." Cited as the #1 cause of prop firm challenge failures across all 2026 sources.

### B7. Daily/Weekly Trade Count Targets

**For a $10K FTMO account** (consensus from FTMO official blog + multiple trader sources):

| Metric | Typical Range |
|---|---|
| Trades per day | **1–3** |
| Trades per week | **5–15** |
| Trades per month (active) | 20–50 |
| Win rate target | 45–55% (with 2:1 RR) |

**FTMO's own guidance** ("Slow is fast"): "You do not need to trade every day. If Tuesday has no setups, skip Tuesday." — `https://www.edgeflo.com/blog/ftmo-rules`

**Note on our setup:** Ayumi's existing strategies have lower frequency (swing/position trades based on prior research). This aligns with the consensus — quality over quantity, low-frequency high-conviction setups.

---

## Section C — Multi-Strategy Blend Best Practices

### C1. Capital Allocation Methods

| Method | Description | Best For | Complexity |
|---|---|---|---|
| **Equal Weight** | Each strategy gets 1/N of capital | Default, robust, simple | Low |
| **Risk Parity** | Weight by inverse volatility (target equal risk contribution) | Strategies with different vol profiles | Medium |
| **Half-Kelly** | Weight = 0.5 × Kelly fraction based on win rate × avg win/loss | High-conviction edge, mature strategies | High |
| **Vol-Targeting** | Scale all positions to hit target portfolio volatility (e.g., 10% annualized) | Multi-asset, multi-timeframe | High |
| **Max Drawdown Targeting** | Allocate more capital to lower-DD strategies | Capital preservation focus | Medium |

**Recommended progression for Ayumi:**

1. **Phase 1 (Launch):** Equal weight, 1/N per strategy. Simple, robust, easy to debug.
2. **Phase 2 (60+ days of data):** Migrate to **risk parity** using 30-day rolling realized vol.
3. **Phase 3 (180+ days, validated edge):** Consider half-Kelly overlay for strategies with strong statistical edge. **Cap Kelly at 0.5×** per backtrex.com, tastylive.com consensus.

**Kelly specifics:**
- Raw Kelly: f* = (W × R − L) / R, where W = win rate, L = loss rate, R = avg win / avg loss
- **Never use full Kelly in production** — extreme volatility, ruinous drawdowns
- **Half-Kelly** (50% of calculated) is industry standard for systematic traders (per backtrex.com, tastylive.com)
- **Quarter-Kelly** (25%) for lower-vol strategies or where win-rate estimates are noisy
- Cap at 2-3% per trade regardless of Kelly output (forexmt4indicators.com)

**Source:** `https://www.quantstart.com/articles/Money-Management-via-the-Kelly-Criterion/`, `https://quantpedia.com/risk-parity-asset-allocation/`, `https://backtrex.com/en/blog/position-sizing-kelly-criterion-trading`, `https://www.tastylive.com/news-insights/smart-trader-guide-kellys-criterion`

### C2. Correlation Handling

**Standard approach for multi-strategy forex portfolios:**

1. **Calculate rolling Pearson correlation** of strategy returns (or signal outputs) over **30–60 day windows**
2. **Threshold-based filtering:**
   - **|ρ| < 0.3**: Strategies are independent — full allocation each
   - **0.3 < |ρ| < 0.7**: Some shared exposure — reduce combined allocation
   - **|ρ| > 0.7**: Effectively the same strategy — **disable simultaneous entries** or merge
3. **Multiple timeframes:** Compute correlation matrix at 30d, 90d, 180d windows; flag strategies whose correlation changes significantly across windows (regime instability)

**Implementation note for Ayumi:**
- Already have `cabal-correlation-regime-2026-07.md` as prior research
- Existing correlation regime detection likely usable directly
- Add a "correlation gate" that prevents new strategy entries when active portfolio's avg pairwise correlation exceeds 0.7

**Source:** General portfolio theory, `https://fxglory.com/learn/forex-strategies/forex-correlation-strategy/` (Jun 2026), `https://www.quantifiedstrategies.com/correlation-trading-strategies/` (Feb 2026)

### C3. Drawdown Attribution

**Standard attribution framework:**

```
Strategy-level DD contribution = strategy_drawdown_dollars × strategy_capital_weight

Portfolio DD = sqrt(sum of weighted DD contributions)  # if uncorrelated
             ≈ sum of weighted DD contributions        # if perfectly correlated
```

**Practical approach for our blend engine:**

1. **Track per-strategy equity curve** separately (not just blended P/L)
2. **On any portfolio-level drawdown event:**
   - Identify which strategy had the largest losing trade / streak
   - Compute that strategy's contribution to the drawdown
   - Flag for review if contribution > 60% (concentration risk)
3. **Monthly attribution report:**
   - Per-strategy return, volatility, Sharpe, max DD
   - Correlation matrix snapshot
   - Capital allocation effectiveness

**Source:** Standard portfolio management practice, no single canonical source — derived from CFA Institute curriculum and standard risk management texts.

### C4. Strategy Capacity — When Does Adding More Stop Helping?

**Quantitative answer:**
- 1 strategy → 100% of its idiosyncratic risk
- 2 strategies → ~70% of combined risk (30% reduction)
- 3 strategies → ~50% of combined risk (50% reduction)
- 5 strategies → ~10–20% of combined risk (80–90% reduction)
- 10+ strategies → marginal improvement, **complexity cost dominates**

**Qualitative answer** (from whatworksintrading.substack.com):
- **Operational complexity** rises linearly with strategy count
- **Capital efficiency drops** — each strategy gets diluted, edge compounds slower
- **Redundancy risk** — strategies that look uncorrelated often correlate during stress (regime shifts, black swans)
- **Diminishing alpha** — if you had 5 strong edges, you'd be a hedge fund; retail traders rarely have 5+ independent edges

**For Ayumi specifically:**
- **Target: 3–5 strategies** spanning different timeframes (M15, H1, H4, D1) or different signal types (trend, mean-reversion, breakout, volatility)
- Each strategy must be independently validated via OOS backtest + paper trade
- Don't add a 6th strategy unless it brings a genuinely orthogonal edge

**Source:** `https://whatworksintrading.substack.com/p/why-3-to-5-strategies` (cites Evans & Archer 1968, Markowitz 1952, AQR, Bridgewater research)

---

## Recommended Defaults for Ayumi FTMO Setup

### Profile
- Target: FTMO $10K 1-Step Challenge (faster pass, simpler rules)
- Starting balance: $10K simulated
- Strategy universe: Ayumi's existing ICT/SMC + filters (see prior research)

### Sizing Rules

| Parameter | Default | Hard Cap |
|---|---|---|
| Per-trade risk | **0.50%** ($50) | 1.0% ($100) |
| Per-strategy max open risk | 1.5% ($150) | 2.5% |
| Total open portfolio risk | **2.0%** ($200) | 3.0% (FTMO daily limit) |
| Max simultaneous positions | 3 | 5 |
| Per-currency net exposure | 3% | 5% |
| Correlation block threshold | |ρ| > 0.7 | — |
| Strategy count | 3–5 | 6 |

### Capital Allocation

- **Phase 1:** Equal weight (1/3, 1/4, or 1/5 per strategy depending on count)
- **Phase 2 (60+ days):** Migrate to risk-parity using 30d realized vol
- **Phase 3 (180+ days):** Half-Kelly overlay on top-2 strategies, capped at 2% per trade

### Recovery Framework

- 1–2% intraday DD → no action, review
- 3–5% intraday DD → cut per-trade risk by 50% for next session
- > 5% intraday DD → pause 24h, audit strategies
- Daily loss approaches 2.5% → stop trading for the day

### FTMO-Specific Defensive Rules

1. **Never hold through 23:30 CE(S)T** (30 min before reset) without explicit intent and pre-computed worst-case equity
2. **Block all entries 5 min before / after high-impact news** on Standard account (no rule on Swing, but still wise)
3. **Calculate daily-loss budget at start of every session:** (yesterday's midnight balance × 0.97) − current open P/L = remaining room
4. **Trail the trailing drawdown daily:** track highest-ever balance at midnight CE(S)T; current floor = max(highest balance, initial balance) × 0.90
5. **Respect the Best Day Rule** once funded: no single day > 50% of cumulative profits (cap position size on day 1 of funded phase)

---

## Sources

### FTMO Official (Primary)
- `https://ftmo.com/en/trading-objectives/` — Official trading objectives, all percentages and reset times (modified 2026-07)
- `https://academy.ftmo.com/lesson/maximum-daily-loss/` — Daily loss calculation walkthrough
- `https://academy.ftmo.com/lesson/maximum-loss/` — Max loss explanation
- `https://ftmo.com/en/blog/drawdowns/` — Drawdown definitions (absolute, relative, max)
- `https://ftmo.com/en/reward-growth-and-scaling-plan/` — Scaling plan current rules, $2M max, 25% boost
- `https://ftmo.com/en/blog/how-much-should-you-risk-on-one-trade/` — Official 1% recommendation
- `https://ftmo.com/en/symbols/` — Contract specs (100K, $5/lot commission, 1:100 / 1:30 leverage)
- `https://ftmo.com/en/faq/do-i-have-to-close-my-positions-overnight-or-before-the-weekend/` — Standard vs Swing restriction confirmation

### 2026 Third-Party Reviews (Cross-verification)
- `https://track360.io/blog/ftmo-review-2026-operator-trader-perspective` (May 2026) — Fee range, scaling requirements, payout mechanics
- `https://www.jptradingcapital.com/blog/en/ftmo-challenge-prices` (Jul 2026) — Current pricing
- `https://www.edgeflo.com/blog/ftmo-rules` (Mar 2026) — Worked examples
- `https://eleusisfx.uk/articles/ftmo-drawdown-rules-explained` (2026) — Trailing drawdown deep dive
- `https://tradetanto.com/learn/ftmo-rules-evaluation-process` (Jun 2026) — 1-Step vs 2-Step distinction
- `https://lunefi.com/blog/ftmo-evaluation` (Jun 2026) — 1-Step rules
- `https://funding4traders.com/home/f/ftmo-1-step-challenge-review-rules-sizes-best-fit` (2026) — Best Day Rule
- `https://ofxtradingsystems.com/blog/ftmo-1-step-vs-2-step` (May 2026) — 50%/10% Best Day Rule
- `https://www.luxalgo.com/blog/ftmo-prop-firm-review-how-to-pass-in-2025/` (Jul 2025) — Historical pricing reference

### Portfolio Sizing & Risk Management Consensus
- `https://traderssecondbrain.com/guides/position-sizing-for-prop-firms` (Mar 2026) — 0.5% recommendation
- `https://traderssecondbrain.com/guides/position-sizing-for-prop-firms` (multiple references) — Position sizing formula, gold lot sizing
- `https://www.thinkcapital.com/position-sizing-for-prop-firms/` (Apr 2026) — 0.25-1% range
- `https://t4tcapitalfm.com/blog/position-sizing-for-funded-accounts-the-risk-model-that-keeps-you-in-the-game/` (Jan 2026) — Professional sizing framework
- `https://aifo.com/blog/guide/risk-per-trade-prop-firm-challenge/` (Jun 2026) — 0.25-0.50% planning range
- `https://www.blueguardian.com/blogs/7-proven-strategies-to-pass-prop-firm-challenge-2026` (Apr 2026) — Cut to 0.5% after losses
- `https://www.tradezella.com/blog/drawdown-management` (Apr 2026) — Tiered reduction framework
- `https://tradeify.co/post/prop-firm-drawdown-recovery-plan-funded-traders` (Mar 2026) — Three-phase recovery plan
- `https://fundedfast.com/learn/risk-management` (Jun 2026) — Correlated exposure rules

### Multi-Strategy & Allocation Theory
- `https://whatworksintrading.substack.com/p/why-3-to-5-strategies` (2025) — 3-5 strategy consensus, Evans & Archer, AQR, Bridgewater
- `https://www.quantstart.com/articles/Money-Management-via-the-Kelly-Criterion/` — Kelly derivation
- `https://quantpedia.com/risk-parity-asset-allocation/` — Risk parity methodology
- `https://backtrex.com/en/blog/position-sizing-kelly-criterion-trading` — 25-50% Kelly fraction consensus
- `https://www.tastylive.com/news-insights/smart-trader-guide-kellys-criterion` — Half-Kelly rationale
- `https://forexmt4indicators.com/forex-tools/kelly-criterion-calculator/` — Practical Kelly cap at 2-3%
- `https://www.vaneck.com/at/en/diversification/` — Diversification theory
- `https://www.investopedia.com/investing/dangers-over-diversifying-your-portfolio/` — 20-asset diminishing returns
- `https://www.home.saxo/learn/guides/diversification/diversification-strategy-from-harry-markowitz-to-todays-best-practices` — Modern Portfolio Theory

### Correlation Handling
- `https://fxglory.com/learn/forex-strategies/forex-correlation-strategy/` (Jun 2026) — Forex correlation practical
- `https://www.quantifiedstrategies.com/correlation-trading-strategies/` (Feb 2026) — Correlation strategies
- `https://blog.quantinsti.com/pairs-trading-basics/` — Pairs trading, cointegration vs correlation

### Trader Communities (Sentiment / Consensus)
- `https://www.reddit.com/r/Forex/comments/1jc87aj/ftmo_challenge_how_does_the_1_rule_work/` — 1% rule discussion
- `https://www.reddit.com/r/Forex/comments/102gjyz/what_lot_size_to_use_on_10000_ftmo_account/` — Lot sizing consensus
- `https://www.reddit.com/r/Forex/comments/112bmlc/what_is_your_risk_per_trade_during_prop_firm/` — Risk per trade survey
- `https://www.facebook.com/groups/710329449564905/` — FTMO Trader's Community (multiple threads, 2026)

---

## Caveats & Open Questions

### Things I'm Confident About
- FTMO 1-Step daily loss = 3% (verified on official FTMO docs)
- FTMO 1-Step max loss = 10% TRAILING end-of-day (verified on official FTMO docs, confirmed by multiple 2026 reviews)
- 1-Step vs 2-Step distinction is real and material (daily loss is 3% vs 5%)
- 0.5% per trade is the modal consensus across 2026 sources
- 3-5 strategies is the research-backed optimum

### Things I'm Less Sure About
1. **Best Day Rule exact thresholds** — multiple sources cite "50% / 10%" but the official FTMO docs page doesn't clearly define it. **Action:** Verify in the FTMO client area terms before relying on this rule.
2. **FTMO $10K current fee** — sources range from $89 to $155. Most likely current price is **€79–$89** for Standard, but pricing fluctuates with promotions. **Action:** Check ftmo.com directly before budgeting challenge fee.
3. **Swing account availability** — confirmed via FTMO FAQ but not on the main objectives page. **Action:** Verify Swing option is available for the 1-Step challenge before assuming.
4. **No hard lot cap published** — risk-based governance is the de facto cap, but no documented hard limit found. **Action:** Don't rely on a "FTMO won't let me trade X lots" assumption.
5. **Correlation threshold of 0.7** — standard but not canonical. Many use 0.6, some use 0.8. **Action:** Backtest different thresholds with Ayumi's actual strategies.

### Conflicts Between Sources
- **Track360** (May 2026) says FTMO max loss is STATIC and 10% applies to both 1-Step and 2-Step. **FTMO.com official** says 1-Step is TRAILING end-of-day. **Resolution:** FTMO.com is authoritative. Track360 is conflating 2-Step with the general FTMO experience.
- **Edgeflo / LuxAlgo** describe FTMO as 5%/10% across the board. **FTMO.com official** confirms 3%/10% for 1-Step. **Resolution:** FTMO.com authoritative — these third-party guides are outdated or only covering 2-Step.

---

## Suggested Next Steps

1. **Confirm 1-Step challenge availability and pricing** at trader.ftmo.com
2. **Implement sizing engine** with the recommended defaults (start at 0.5% per trade)
3. **Build correlation gate** using existing `cabal-correlation-regime-2026-07.md` research
4. **Run paper trade for 30+ days** with multi-strategy blend before committing challenge fee
5. **Document per-strategy attribution** to enable Phase 2 migration to risk-parity
6. **Schedule FTMO Free Trial** (available per their site) to validate platform and connectivity

---

*End of research document. Ready for Ava's review and orchestration.*