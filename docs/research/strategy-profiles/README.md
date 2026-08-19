# Strategy Profiles — Regime Characterization Matrix

> **Created:** 2026-07-22
> **Data source:** DuckDB `ayumi_market.duckdb`, XAUUSD M15 (71,747 bars) + H1 (17,948 bars)
> **Raw report:** `/tmp/regime_profiles.md` (701 lines, 45 tables)
> **Method:** Bar-by-bar evaluation, $50 risk/trade, 3-leg partial exits (1R/2R/3R), 50-bar time stop

---

## Executive Summary

Two strategies are net profitable on XAUUSD M15 with current configs. Three need regime gating or rework.

| Strategy | M15 Net | M15 PF | M15 WR | H1 Net | H1 PF | Status |
|---|---|---|---|---|---|---|
| KillzoneMomentum | **+$2,265** | **1.08** | 42.4% | -$1,167 | 0.84 | ✅ Profitable M15 |
| DualTFSqueezePro | **+$652** | **1.02** | 45.2% | $0 | — | ✅ Marginal M15 |
| DonchianATRTrendV2 | -$5,882 | 0.90 | 40.6% | **+$1,733** | **1.12** | ⚠️ Profitable H1 only |
| SRMRPlus | -$5,177 | 0.70 | 31.6% | -$4,772 | 0.42 | ❌ Needs rework |
| VolatilityRegimeBreakout | +$25 | 1.50 | 50% | +$133 | ∞ | ⚠️ Only 3 trades — insufficient data |

---

## Per-Strategy Sweet Spots

### KillzoneMomentum (M15) — PROFITABLE
- **Best regime:** QUIET (PF=3.00, WR=66.7%, +$900)
- **Good regime:** CHOPPY (PF=1.56, WR=50%, +$483)
- **Best ADX:** 20-25 (PF=1.53, +$4,191) — THIS is the sweet spot
- **Best ATR pct:** 0-20 (PF=3.00)
- **Best session:** London (PF=1.23)
- **Best hours:** 0-4 UTC (PF=1.42)
- **BLEEDS:** ADX 30-40 (PF=0.80, -$1,656), ATR 50-80 (PF=0.89)
- **Recommended gate:** `regime ∈ {quiet, choppy} AND ADX ∈ [18, 25] AND session ∈ {london}`

### DualTFSqueezePro (M15) — MARGINALLY PROFITABLE
- **Best regime:** VOLATILE (PF=1.10, WR=47.5%, +$896)
- **Good regime:** CHOPPY (PF=1.04, +$417)
- **Best ADX:** 40+ (PF=1.93, +$417)
- **Best ATR pct:** 80-100 (PF=1.10, +$896)
- **Best session:** Asia (PF=1.11, +$1,167)
- **Best hours:** 0 UTC (PF=1.14, +$850)
- **BLEEDS:** London session (PF=0.88, -$1,117), Hours 8 UTC (PF=0.86, -$1,083)
- **Recommended gate:** `session ∈ {asia, ny_am} AND regime ∈ {volatile, choppy}`

### DonchianATRTrendV2 (H1) — PROFITABLE ON H1
- **H1 result:** +$1,733, PF=1.12 (233 trades)
- **H1 best regime:** QUIET (PF=1.00, break-even) and TRENDING with ADX 20-25
- **M15 result:** -$5,882, PF=0.90 — loses on M15
- **Recommended:** Trade on H1 only, gate to `ADX < 30 AND ATR_pct < 50`

### SRMRPlus — NEEDS REWORK
- Loses on both timeframes. Only profitable in QUIET regime M15 (PF=1.25, +$521) and London session (PF=1.07, +$397).
- Massive bleed in NY AM session: PF=0.52, -$5,574
- **Recommended:** Drop from blend OR gate extremely tightly (`regime=quiet AND session=london`)

### VolatilityRegimeBreakout — INSUFFICIENT DATA
- Only 3 trades total on XAUUSD. Cannot profile.
- Needs parameter relaxation or different pair testing before conclusions.

---

## Complementary Blend Candidates

**Blend A — KZ + DualTF (M15):**
- KZ wins in QUIET/CHOPPY + London + ADX 20-25
- DualTF wins in VOLATILE + Asia + ADX 40+
- Correlation: -0.00 (essentially uncorrelated)
- Combined coverage: QUIET + CHOPPY + VOLATILE regimes, London + Asia sessions

**Blend B — KZ + DualTF + Donchian H1:**
- Add Donchian on H1 for trend-following coverage
- Donchian H1 is profitable (+$1,733) and covers different timeframe
- Three-way diversification across regime + session + timeframe

---

## Next Steps
1. Run gated blend backtest (Blend A and B) with regime/session gates applied
2. If profitable → add confidence layer (spread gates, volatility gates)
3. Validate with Monte Carlo + walk-forward on the GATED blend
4. Profile on EURUSD + GBPUSD to find cross-pair opportunities

**UPDATE Jul 22:** Steps 1-4 complete. Gated blend passes FTMO (PF=1.74, MC 99.9%). FX profiling shows no edge on EURUSD/GBPUSD with current XAUUSD-tuned params. Trade volume gap: 38/year vs 250/year needed.

**Expansion priorities (Craig directive Jul 22):**
1. Symbol expansion — USDJPY (harvesting now), FX retuning
2. Strategy expansion — B.3 London Breakout, FX-native variants, mean-reversion
3. Optuna parameter optimization per strategy × symbol × regime
4. Confidence engine wiring (spread/vol/session gates on top of regime gates)

---

## Raw Data
Full 701-line report with all 45 tables lives at: `/tmp/regime_profiles.md`
Key sections: per-regime, per-session, per-hour (4h UTC buckets), per-ADX-range, per-ATR-percentile-range for each strategy × timeframe.
