# Ayumi Multi-Strategy Blend Plan — 2026-07

**Author:** Ava Daigo
**Date:** 2026-07-12
**Status:** Active — integrating FTMO research findings
**Parent:** FTMO research doc (`docs/research/ftmo-risk-and-port-sizing-2026-07.md`), Strategy research (`docs/research/strategy-optimization-research.md`)

---

## TL;DR

We're building a **3-layer multi-strategy portfolio** for FTMO $10K 1-Step Challenge:
1. **Swing layer (M15/H1)** — high-conviction, sparse (3-15 trades/month per strategy), WR ≥ 65%, PF ≥ 2.0
2. **Frequency layer (M3/M5)** — high-frequency, tighter stops (15-30 trades/month per strategy), WR 40-55%, PF 1.3-2.0
3. **Portfolio blend** — 3-5 strategies combined with risk-weighted allocation

**Hard constraints from FTMO 1-Step:**
- 3% daily loss limit
- 10% TRAILING end-of-day max loss (the killer — see "FTMO Trap" below)
- 1:100 leverage Standard / 1:30 Swing
- Reset at 00:00 CE(S)T (Toronto is UTC-4, reset is 6 hours ahead)

**Defaults (per FTMO research §B + Craig directive):**
- Per-trade risk: 0.5% ($50 on $10K)
- Max simultaneous: 3 (hard cap 5)
- Total open risk: ≤ 2%
- Per-currency net exposure: ≤ 3%
- Correlation block: |ρ| > 0.7 → disable simultaneous
- Strategy count: 3-5
- Target trade count: ≥ 30 trades/month blended
- Allocation: equal weight initially, migrate to risk-parity at 60+ days

---

## The FTMO Trap — Why This Matters

FTMO's 1-Step Challenge has a **TRAILING end-of-day max loss** at 10% of initial capital. This means:

- Day 1: floor at $9,000 (initial - 10%)
- Day 5: balance at $10,800 → floor moves to $9,720
- Day 9: balance at $11,200 → floor moves to $10,080
- Day 15: balance drops to $10,300 → floor STAYS at $10,080 → only $220 room
- Day 16: a $250 loss → **challenge ends** despite still being in profit from start

**Implication for our blend:** We MUST track the highest midnight balance and compute the trailing floor daily. The blend engine needs a "FTMO guard" that warns when open risk approaches the floor.

**2-Step alternative:** 10% STATIC max loss — easier to pass. Consider 2-Step as a safer option if 1-Step trailing math gets hairy.

---

## Strategy Universe (current + proposed)

### Existing strategies with sweep data (2026-07-12)

| Strategy | Best Symbol/TF | WR | PF | Trades | Status |
|---|---|---|---|---|---|
| ttc_xauusd | XAUUSD M15 | 47% | 2.25 | 31 | **Verify** — §C.3 anomaly |
| ttc_xauusd | XAUUSD M5 | 46% | 1.46 | 61 | Active |
| bb_rsi_reversion | GBPUSD M15 (tick) | 50% | 5.55 | 7 | Sparse swing |
| bb_rsi_reversion | GBPUSD H1 (tick) | 37% | 2.24 | 21 | Active |
| killzone_momentum | EURUSD H1 | 27% | 2.06 | 8 | Sparse swing |
| killzone_momentum | GBPUSD H1 | 27% | 2.04 | 7 | Sparse swing |
| london_breakout_retest | EURUSD M15 | 40% | 4.00 | 6 | Sparse swing |

### New strategies built this session

| Strategy | Type | Standalone signals | Status |
|---|---|---|---|
| donchian_atr_trend | Trend-following | 212/4900 bars | Active, needs tuning |
| london_breakout_retest | Session breakout | 73/9800 bars | Active, real edge |

### Still to build (Tsukasa cards)

- **dual_tf_squeeze_pro** — replaces volatility_squeeze contradictions
- **Per-pair presets for killzone_momentum** — M5 vs H1 thresholds
- **bb_rsi_reversion tuning OR deprecation** — research §A.6 says deprecate

### Final blend candidate list (target: 3-5)

Picking from validated winners, with frequency mix:

**Tier 1 — Swing layer (sparse, high WR):**
- `ttc_xauusd` XAUUSD M15 (pending verification)
- `killzone_momentum` EURUSD H1 (or GBPUSD H1)
- `bb_rsi_reversion` GBPUSD H1 (tick data — real edge)

**Tier 2 — Frequency layer (higher count):**
- `donchian_atr_trend` M5 (tuned)
- `ttc_xauusd` XAUUSD M5 (61 trades, decent WR)

**Tier 3 — Session layer (occasional):**
- `london_breakout_retest` EURUSD M15

Pick 3-5 of these based on correlation analysis once blend engine runs.

---

## Phasing

### Phase A — Foundations (READY/IN PROGRESS)

| Card | Owner | Status |
|---|---|---|
| Download XAUUSD tick data | Ava (self) | Ready (497ac668) |
| Download EURUSD tick data | Ava (self) | Ready (b0c89298) |
| Add M3 timeframe | Tsukasa | Ready (c1bf1d43) |
| Fix volatility_squeeze session filter | Tsukasa | Ready (485cfa5f) |
| Build portfolio blend driver script | Tsukasa | Ready (ab85f3e8) |

### Phase B — Strategy hardening

| Card | Owner | Status |
|---|---|---|
| Apply research tuning to remaining strategies | Tsukasa | Ready (59011a7a) |
| Build dual-TF squeeze pro | Tsukasa | Ready (e5a9f9b0) |
| Investigate ttc_xauusd anomaly | Tsukasa | Ready (13ceadb0) |

### Phase C — Blend simulation (after Phase B lands)

1. Run sweep on full tick data (all 3 symbols × M3/M5/M15/H1)
2. Select 3-5 best candidates based on:
   - Per-strategy go/no-go (PF ≥ 1.3, WR ≥ 45% for freq, ≥ 65% for swing)
   - Pairwise correlation < 0.7
   - Per-symbol max 2 strategies (avoid concentration)
   - Monthly blended trade count ≥ 30
3. Run portfolio blend simulation with `equal_risk` weights
4. Verify portfolio-level gates pass: combined PF ≥ 1.3, combined WR ≥ 55%, max DD ≤ 5%

### Phase D — FTMO guard + paper trade

1. Build "FTMO guard" module: tracks highest midnight balance, computes trailing floor, blocks new entries if total open risk > 50% of remaining floor
2. Best Day Rule tracker: warn if any day's profit > 50% of cumulative (after funded phase)
3. News blackout: 5 min before/after high-impact events
4. Paper trade for 30+ days, monitor metrics, then commit challenge fee

---

## Risk Rules (locked in for blend engine)

### Per-trade
- Default: 0.5% of account ($50 on $10K)
- Hard cap: 1.0% ($100)
- Per-strategy: 1.5% max open risk
- Total portfolio: ≤ 2% open risk

### Recovery framework (tiered)
| Intraday DD | Action |
|---|---|
| < 1% | No change |
| 1-2% | Review last 3 trades |
| 3-5% | Cut per-trade risk to 0.25% for next session |
| > 5% | Pause 24h, audit strategies |
| Daily approaches 2.5% | Stop trading for day |

### FTMO-specific defensive rules
1. **Never hold through 23:30 CE(S)T** without explicit intent + pre-computed worst-case equity
2. Block entries 5 min before/after high-impact news (Standard account)
3. Compute daily-loss budget at session start: (yesterday's midnight balance × 0.97) − current open P/L = remaining room
4. Trail the trailing drawdown: track highest-ever midnight balance; floor = max(highest balance, initial balance) × 0.90
5. Best Day Rule (once funded): no single day > 50% of cumulative profits

### Currency exposure
- Max 3% net exposure per single currency (e.g., EURUSD + EURGBP combined)
- Treat CHF + JPY as combined safe-haven exposure (correlation ~0.7)

---

## Allocation Methods (progression)

**Phase 1 (Launch, 0-60 days):**
- Equal weight: 1/N per strategy
- Simple, robust, easy to debug
- Allows comparing strategy performance cleanly

**Phase 2 (60+ days of live data):**
- Migrate to risk-parity using 30d rolling realized vol
- Weights: w_i = (1/vol_i) / sum(1/vol_j)
- Each strategy contributes equal risk, not equal capital

**Phase 3 (180+ days, validated edge):**
- Half-Kelly overlay on top-2 strategies
- Kelly formula: f* = (W × R − L) / R
- Cap at 2% per trade regardless of Kelly output
- **NEVER use raw Kelly** — too aggressive, causes ruin

---

## Correlation Handling

Threshold-based filtering (per FTMO research §C.2):
- |ρ| < 0.3: independent, full allocation
- 0.3 < |ρ| < 0.7: reduce combined allocation
- |ρ| > 0.7: disable simultaneous entries or merge

Compute rolling Pearson correlation of strategy returns over 30d window. If active portfolio's avg pairwise correlation > 0.7, block new entries until correlation drops.

---

## Strategy Count: Why 3-5

Research-backed optimum (Evans & Archer 1968, AQR, Bridgewater):
- 1 strategy → 100% of its risk
- 3 strategies → ~50% risk reduction
- 5 strategies → 80-90% of total possible risk reduction
- 10+ → complexity cost dominates, marginal benefit

**Ayumi target:** 3-5 strategies spanning:
- Different timeframes (M3, M5, M15, H1)
- Different signal types (trend, mean-reversion, breakout, volatility)
- Different market conditions (session-based vs always-on)

---

## Data Requirements

### Currently have
- GBPUSD tick data: 117M rows, 2020-01 to 2025-04
- 1.96M GBPUSD bars pre-aggregated (M1 through D1)

### To acquire (Ava self)
- XAUUSD ticks (Dukascopy, ~2-3 hours)
- EURUSD ticks (Dukascopy, ~2-3 hours)

### Why real ticks only
- CSV has zero spread, zero volume, no session info
- Strategies with session filters (`volatility_squeeze`, `london_breakout_retest`) need session-aware bar construction
- Spread modeling is critical for realistic P/L

---

## Verification Checklist (Phase C)

Before committing to FTMO challenge fee:

- [ ] All selected strategies pass per-strategy go/no-go (PF ≥ 1.3)
- [ ] Pairwise correlation of selected strategies < 0.7
- [ ] Monthly blended trade count ≥ 30 (per Craig directive)
- [ ] Combined portfolio PF ≥ 1.3
- [ ] Combined portfolio max DD ≤ 5% (well under FTMO 10% trailing)
- [ ] 30+ days paper trading validates backtest assumptions
- [ ] FTMO guard tracks trailing floor correctly
- [ ] News blackout wired
- [ ] Best Day Rule tracker wired

---

## Open Questions / Decisions Needed

1. **1-Step vs 2-Step challenge?** 1-Step has trailing max loss (harder) but single phase (faster pass). 2-Step has static max loss (easier) but two phases. Recommend 2-Step for first attempt.
2. **Standard vs Swing account?** Standard = 1:100 leverage but no overnight/weekend. Swing = 1:30 leverage but full freedom. Recommend Standard for our M5/M15/H1 strategies (no overnight needed).
3. **Best Day Rule verification** — flagged in research doc. Verify in FTMO client area before relying on it.
4. **Swing availability for 1-Step** — verify in FTMO portal before assuming.

---

## Card Index

All Phase A/B work is on the workboard with proper frontmatter:

- `497ac668` — XAUUSD tick download (Ava)
- `b0c89298` — EURUSD tick download (Ava)
- `c1bf1d43` — M3 timeframe support (Tsukasa)
- `485cfa5f` — volatility_squeeze session fix (Tsukasa)
- `ab85f3e8` — Portfolio blend driver script (Tsukasa)
- `59011a7a` — Research tuning apply (Tsukasa)
- `e5a9f9b0` — Dual-TF squeeze pro (Tsukasa)
- `13ceadb0` — TTC anomaly investigation (Tsukasa)

---

*Last updated: 2026-07-12 by Ava. Update when phase gates complete or risk rules change.*