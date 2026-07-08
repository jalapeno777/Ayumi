# Quest Phase Update — 2026-07-08 16:02 EDT

## Craig Directive
Major quest expansion. Data infrastructure is a critical gap. All pending items should be folded into quest objectives. Council must review the full picture.

---

## New Quest Phases (proposed)

### Phase 8: Database Infrastructure
**Goal:** Replace CSV/file-based data storage with a proper time-series database.

**Tasks:**
1. Database selection (TimescaleDB vs ClickHouse vs DuckDB vs InfluxDB)
   - Must support: live tick ingestion, historical bar queries, M1→any-TF synthesis, 10+ years of data
   - Consider: storage efficiency, query speed, operational complexity, Python ecosystem support
2. Database setup and configuration
3. Schema design (ticks, bars, signals, trades, walk-forward results)
4. Migration of existing CSV/parquet data into DB
5. Live tick logging from cTrader forward test → DB
6. Optimization (indexing, partitioning, retention policies)

**Acceptance:** DB running, all existing historical data imported, live ticks persisting, query performance validated.

### Phase 9: Historical Data Acquisition
**Goal:** Download 10-15 years of M1 data for all trading pairs.

**Tasks:**
1. Build Dukascopy download script (M1 bars for XAUUSD, GBPUSD, EURUSD, USDJPY)
2. Download 2008-2023 M1 data (leave 2023-2026 as true OOS holdout)
3. Import into database
4. Build timeframe synthesis pipeline (M1 → M3, M5, M10, M15, M30, H1, H4)
5. Data quality validation (gap detection, timestamp integrity, price sanity checks)
6. Verify MinBTL constraint satisfaction (30 trials × 10+ years = compliant)

**Acceptance:** 10+ years of M1 data for 4 pairs in DB, synthesized timeframes available, quality validated.

### Phase 10: Testing Pipeline Upgrade
**Goal:** Update all testing scripts to use the database instead of CSV files.

**Tasks:**
1. Update `data_loader.py` to read from DB (with CSV fallback)
2. Update walk-forward runner to query DB for arbitrary timeframes
3. Update Optuna pipeline scripts to pull from DB
4. Add ICIR computation to WF evaluation (M5/M15 strategies with 30+ windows)
5. Implement OOS gate (Deflated Sharpe Ratio) as post-WF filter
6. Update multi-strategy WF evaluation script
7. Add ICIR live monitoring to forward test

**Acceptance:** All testing scripts query DB, ICIR computed for M5/M15, DSR gate operational, live ICIR monitor active.

### Phase 11: Council Review & Synthesis
**Goal:** Council reviews all research findings and infrastructure plans before execution.

**Topics for review:**
1. ICIR research findings — applicability to our system
2. OOS gate research — DSR implementation, multiple testing correction
3. Database infrastructure plan — selection, schema, migration
4. Dukascopy data acquisition plan — scope, timeframes, OOS holdout strategy
5. Testing pipeline upgrade — what changes, what stays
6. Impact on existing quest phases — dependencies, resequencing

**Acceptance:** Council provides feedback, Ava synthesizes, Craig approves final plan.

---

## Impact on Existing Phases

| Phase | Impact | Notes |
|-------|--------|-------|
| Phase 3 (multi-strategy validation) | **Blocked** until Phase 10 completes | Need DB + more data for proper WF + ICIR |
| Phase 7 (FTMO challenge run) | **Blocked** until Phase 10 + Phase 3 complete | Need validated multi-strategy portfolio |
| Phase 1B (Hayate checkpoints) | **Enhanced** — 9 unimplemented checkpoints can use DB | Live data sources become available |
| Forward test | **Enhanced** — starts logging ticks to DB | No code change needed to forward test itself |

## SRMR+ Results (preserved)
9 viable streams committed and promoted to forward test config. These survive the pivot — they become the baseline to re-validate once DB + more data is available.

## Research Findings (preserved)
- ICIR: viable for M5/M15 with 30+ windows. Best use: live decay monitor. ~3-4 days to implement.
- OOS Gate: DSR is the highest-value addition. ~1 day to implement. 9 SRMR+ streams likely contain 3-5 false positives — deploy as portfolio, let live data filter.
- Multiple testing: 160 evaluations needs BH-FDR correction at viable stage, Holm at deployment stage.
