# Ayumi Master Roadmap — Canonical Source of Truth

> **This document supersedes all prior plan, quest, and roadmap documents.**
> If any other doc conflicts with this one, this one wins.
> Last updated: 2026-07-13

---

## Objective

Build and run a profitable automated forex trading bot on the **FTMO 1-Step Standard $10,000** challenge, pass it, and get funded.

## FTMO Profile (LOCKED)

| Parameter | Value |
|-----------|-------|
| Account type | 1-Step Standard |
| Starting balance | $10,000 |
| Daily loss limit | 5% ($500) |
| Max total loss | 10% ($1,000) |
| Profit target | 10% ($1,000) |
| Min trading days | 0 (no minimum) |
| Profit split | 90% |
| Leverage | 1:30 (retail) |
| Max position size | Per FTMO symbol limits |

---

## Current State (2026-07-13)

### What We Have

**Data Layer:**
- DuckDB (`ayumi_market.duckdb`, 53GB): 429M ticks, 306M bars
- Coverage:
  - EURUSD: M5/M15/H1 ticks (2020-01 → 2026-07) ✅
  - GBPUSD: M1-M30/H1/H4/D1 (2020-01 → 2025-04) ⚠️ stale (Apr 2025 cutoff)
  - XAUUSD: M5/M15/H1 ticks (2022-01 → 2026-07) ✅
  - USDJPY: ❌ NO DATA
- Research DB (`research.duckdb`): 8 strategies, 144 walk-forward runs

**Strategies (16 built, 8 with edge docs + SRF runs):**
- Tier 1 (validated): `volatility_regime_breakout` (27 runs), `volatility_squeeze` (27 runs), `srmr_plus` (25 runs), `ttc_xauusd` (21 runs), `killzone_momentum` (17 runs)
- Tier 2 (initial runs): `bb_rsi_reversion` (9), `donchian_atr_trend` (9), `london_breakout_retest` (9)
- Tier 3 (built, no SRF): `momentum`, `mtf_filtered_momentum`, `rsi_threshold`, `session_breakout`, `session_range_mean_reversion`, `session_range_mr_ict_filtered`, `dual_tf_squeeze_pro`

**Infrastructure:**
- cTrader order chain proven (Jun 25, 2026)
- Forward test infrastructure with health monitoring
- Risk engine: position sizing, kill switch, FTMO guard, daily audit
- SRF framework: walk-forward, Monte Carlo, PBO, parameter stability
- Quant: bootstrap CIs, multiple testing correction, ICIR, OOS gate

### What's Missing

| Gap | Impact |
|-----|--------|
| No USDJPY data | Can't trade USDJPY (target pair) |
| GBPUSD data stale (Apr 2025) | Can't validate GBPUSD strategies |
| No canonical test runbook | Unclear what to run, when |
| No data pipeline runbook | Unclear how to download/aggregate/validate |
| No final strategy blend selected | Can't launch forward test |
| Portfolio blend driver not wired | Can't run multi-strategy forward test |
| FTMO trailing guard not implemented | Risk of breaching max loss |
| No M3 timeframe data | Some strategies may need it |
| No news blackout | Risk of trading into volatility spikes |
| No CI/CD | No automated test runs on push |

---

## Phase Plan: Now → FTMO Challenge

### Phase 0: Data Completeness (1-2 days)
> Goal: Fill data gaps so all target pairs have complete coverage.

- [ ] **0.1** Download USDJPY tick data (Dukascopy, 2020-01 → present)
- [ ] **0.2** Update GBPUSD data (Dukascopy, 2025-04 → present)
- [ ] **0.3** Aggregate ticks → bars for USDJPY (M5, M15, H1, H4, D1)
- [ ] **0.4** Validate data quality (gap analysis, tick density, spread sanity)
- [ ] **0.5** Download Dukascopy crisis period data (2020-03 COVID, 2022-02 Ukraine) for stress testing

**Target pairs:** EURUSD, GBPUSD, USDJPY, XAUUSD
**Target timeframes:** M5, M15, H1, H4, D1

### Phase 1: Strategy Validation (3-5 days)
> Goal: Select the final 3-5 strategy blend via rigorous walk-forward + quant analysis.

- [ ] **1.1** Run SRF walk-forward for all 8 Tier 1+2 strategies across 4 pairs × 6 years
- [ ] **1.2** Run Monte Carlo on top performers (1,000 simulations min)
- [ ] **1.3** Run PBO (Probability of Backtest Overfitting) on each strategy
- [ ] **1.4** Run multiple testing correction (Bonferroni/Holm) across strategy set
- [ ] **1.5** Generate correlation matrix of strategy returns (exclude >0.7 correlated)
- [ ] **1.6** Score each strategy: OOS Sharpe, max DD, profit factor, PBO, ICIR
- [ ] **1.7** Select final blend: 3-5 strategies, diversified across pairs/timeframes
- [ ] **1.8** Document selection rationale in `docs/decisions/strategy-blend-selection.md`

**Gate:** Blend selected → Phase 2. If no strategy passes, go back to strategy development.

### Phase 2: Blend Engine + Risk Wiring (2-3 days)
> Goal: Wire the selected blend into a single executable forward-test system.

- [ ] **2.1** Wire portfolio blend driver to forward test launcher
- [ ] **2.2** Implement FTMO trailing drawdown guard (track highest balance, floor at 90%)
- [ ] **2.3** Implement daily loss budget computation at session start
- [ ] **2.4** Implement news blackout (block entries ±5 min around high-impact events)
- [ ] **2.5** Implement per-strategy freeze (stop trading a strategy after N consecutive losses)
- [ ] **2.6** Implement currency exposure cap (max 3% net per currency)
- [ ] **2.7** Wire kill switch to blend driver (auto-stop on daily DD breach)
- [ ] **2.8** Run blend backtest with FTMO simulation across 2020-2026 data

**Risk Rules (LOCKED):**
- Per-trade: 0.5% default ($50), 1.0% hard cap ($100)
- Per-strategy: 1.5% max open risk
- Portfolio: ≤2% total open risk
- Recovery: 1-2% DD → review; 3-5% → cut to 0.25%; >5% → pause 24h
- Daily approaches 2.5% → stop trading for day
- Never hold through 23:30 CE(S)T without explicit intent
- Best Day Rule (once funded): no single day >50% of cumulative profit

**Gate:** Blend backtest passes FTMO sim (profit > 10%, max DD < 10%, daily DD < 5%) → Phase 3.

### Phase 3: Paper Trading Validation (1-2 weeks)
> Goal: Validate the blend runs correctly on cTrader demo account.

- [ ] **3.1** Deploy blend to cTrader demo account
- [ ] **3.2** Run for minimum 5 trading days
- [ ] **3.3** Verify: signals fire correctly, positions open/close, TP/SL set, risk respected
- [ ] **3.4** Daily audit: check P&L, DD, signal quality, execution quality
- [ ] **3.5** Fix any issues found (latency, slippage, missed signals, etc.)

**Gate:** 5 clean trading days with no execution errors → Phase 4.

### Phase 4: FTMO Challenge Run (ongoing)
> Goal: Pass the FTMO 1-Step Standard $10K challenge.

- [ ] **4.1** Open FTMO 1-Step Standard $10K account
- [ ] **4.2** Deploy blend with live FTMO credentials
- [ ] **4.3** Run daily audit every trading day
- [ ] **4.4** Monitor: daily DD, total DD, profit progress, signal quality
- [ ] **4.5** Kill switch armed at all times
- [ ] **4.6** Pass challenge (10% profit, within DD limits)

**Gate:** Challenge passed → Phase 5 (funded trading).

### Phase 5: Funded Trading (ongoing)
> Goal: Generate consistent returns on funded account.

- [ ] **5.1** Switch to funded credentials
- [ ] **5.2** Scale per-trade risk per FTMO scaling plan
- [ ] **5.3** Weekly performance review
- [ ] **5.4** Monthly strategy review (re-validate edge, re-run walk-forward if needed)
- [ ] **5.5** Quarterly data refresh (download latest ticks, re-aggregate)

---

## Data Pipeline

### Download → Aggregate → Validate

```
1. Download ticks (Dukascopy)
   scripts/download_dukascopy.py --pair <PAIR> --start <DATE> --end <DATE>
   scripts/download_dukascopy_crisis.py  # for crisis periods

2. Import ticks to DuckDB
   scripts/import_ticks.py --pair <PAIR> --input <TICK_FILE>

3. Aggregate ticks → bars
   scripts/aggregate_ticks_to_bars.py --pair <PAIR> --timeframes M5,M15,H1,H4,D1

4. Validate
   scripts/health_check_tick_pipeline.py --pair <PAIR>
   scripts/qa_market_data.py --pair <PAIR>  # gap analysis, density check
```

### DuckDB Schema

- `ticks`: symbol, timestamp_ms, bid, ask, spread
- `bars`: symbol, timeframe, timestamp_utc, open, high, low, close, volume, spread_pips
- `import_log`: import audit trail

---

## Test Runbook

### Quick Check (before any commit)
```bash
source .venv/bin/activate
python3 -m pytest tests/unit/ -q -x --timeout=30
```

### Strategy Tests (when touching strategies)
```bash
source .venv/bin/activate
python3 -m pytest tests/strategies/ -q -x --timeout=30
```

### Integration Tests (when touching cTrader/adapters)
```bash
source .venv/bin/activate
python3 -m pytest tests/integration/ -q -x --timeout=30 -m "not live"
```

### Full Suite (before merge to main, requires --full flag)
```bash
source .venv/bin/activate
python3 -m pytest tests/ -q --timeout=30 -m "not live"
```

### SRF Walk-Forward (when validating strategies)
```bash
source .venv/bin/activate
python3 -m pytest tests/unit/srf/ -q -x
# Or run a specific strategy:
python3 -m src.forex-bot.srf.runner --strategy srmr_plus --pair EURUSD --start 2020-01-01 --end 2026-07-01
```

### What NOT to run
- Never run bare `pytest tests/` during development — use targeted scope
- Never run `tests/e2e/test_live_*.py` without `--live` flag and explicit reason
- Never run SRF sweeps on full 6-year data during development (use 1-year sample first)

---

## Repo Structure (Cleaned 2026-07-13)

```
Ayumi/
├── src/forex-bot/          # Main codebase (300 files)
│   ├── adapters/           # cTrader, Open API
│   ├── analytics/          # Regime, correlation, session, patterns
│   ├── backtest/           # Engine, walk-forward, portfolio blend, FTMO guard
│   ├── common/             # Shared utilities
│   ├── config/             # Configuration
│   ├── core/               # Engine core, types, indicators
│   ├── data/               # Data layer
│   ├── engine/             # Signal engine
│   ├── forward_test/      # Forward test infrastructure
│   ├── ml/                 # ML pipeline
│   ├── quant/              # Quant analysis (ICIR, OOS, calibration, DSR)
│   ├── risk/               # Risk engine, FTMO guard, kill switch
│   ├── signal_engine/      # Signal generation and routing
│   ├── srf/                # Strategy Research Framework
│   └── strategies/         # 16 strategy implementations
├── tests/                  # 5,800+ tests
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   ├── strategies/
│   └── regression/
├── scripts/                # Pipeline scripts (to be cleaned further)
├── docs/                   # Documentation
│   ├── audits/             # This inventory + audits
│   ├── decisions/          # Decision records
│   ├── edges/              # Strategy edge hypotheses
│   ├── plans/              # (legacy — superseded by this roadmap)
│   ├── research/           # Research docs
│   └── runbooks/           # Operational runbooks
├── data/                   # DuckDB + SQLite + Parquet
├── reports/                # Backtest reports
├── config/                 # Config files
├── pytest.ini
├── ruff.toml
├── requirements.txt
└── TOOLS.md
```

---

## Superseded Documents

These docs are now **historical reference only**. Do not use them as source of truth:

- `docs/plans/quest-ayumi-ftmo-2026-07-07.md`
- `docs/plans/quest-ayumi-ftmo-roadmap-2026-07-08.md`
- `docs/plans/quest-ayumi-ftmo-phase-update-2026-07-08.md`
- `docs/plans/quest-ayumi-ftmo-reviews-synthesis-2026-07-08.md`
- `docs/plans/quest-pivot-final-synthesis-2026-07-08.md`
- `docs/plans/multi-strategy-blend-plan-2026-07.md`
- `docs/plans/ayumi-refactor-2026-06.md`
- `docs/plans/ayumi-refactor-2026-06-full-spec.md`
- `docs/plans/ayumi-reliability-sprint-2026-07-05.md`
- All other `docs/plans/sprint-*.md` and `docs/plans/bq*.md` files

**Keep as reference** (still contain useful detail):
- `docs/research/ftmo-risk-and-port-sizing-2026-07.md` — FTMO risk rules detail
- `docs/edges/*.md` — Strategy edge hypotheses
- `docs/audits/*.md` — Recent audit findings
- `docs/post-mortems/*.md` — Learning from past failures

---

*This is the canonical roadmap. All work should trace back to a phase and task here. If it's not in this roadmap, it doesn't get done.*
