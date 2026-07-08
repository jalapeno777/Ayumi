# Final Synthesis — Council Review + Quest Pivot Plan

**Author:** Ava (synthesizing Rei + Sora + Kaito reviews + own analysis)
**Date:** 2026-07-08 16:28 EDT
**Status:** For Craig approval

---

## Council Verdict: APPROVE-WITH-FINDINGS

All three reviewers agree the pivot direction is correct. The disagreements are on execution.

---

## Key Agreements (all 3 reviewers)

1. **Don't block Phase 3 on infrastructure work.** The 9 SRMR+ streams are already in the forward test. Keep validating strategies on existing data in parallel with DB/data work.
2. **DSR should be applied NOW** as a post-hoc annotation on the 9 existing streams, not deferred to a pipeline rewrite.
3. **DuckDB alone can't handle live tick ingestion.** Single-writer model conflicts with concurrent backtest + live write.
4. **Council review should come BEFORE implementation, not after.** Phase 11 ordering was backwards.
5. **Data QA spec needed before bulk Dukascopy download.** Gap detection, regime flags, cross-validation against cTrader.

---

## Key Disagreements & Resolutions

### DB Architecture: DuckDB vs Hybrid vs ClickHouse

| Reviewer | Position | 
|----------|----------|
| Ava (synthesis v1) | DuckDB for everything |
| Sora | Hybrid (live store + DuckDB analytical) or ClickHouse |
| Kaito | DuckDB for analytics, SQLite stays for trades — two-DB coexistence |
| Rei | No strong opinion, wants decision matrix |

**Resolution: Two-DB strategy (Kaito's position, enhanced by Sora's tick-volume analysis)**

- **SQLite stays** for trade store, equity curve, workboard, Optuna studies (already in production, working, WAL mode)
- **DuckDB** for market data analytics (historical bars, WF queries, Optuna data source)
- **Live tick logging:** Write to Parquet files (append-only, one per day), DuckDB reads them natively. No concurrent writer problem. Simple, no server.
- **No ClickHouse/TimescaleDB** — operational overhead not justified at our scale (~100 ticks/sec, not 100K)
- If tick volume ever exceeds Parquet's comfort zone (>1B rows), revisit then

This avoids Sora's concurrency concern (DuckDB never has a live writer — it reads Parquet files), respects Kaito's coexistence requirement (SQLite untouched), and keeps Rei happy (no new server process).

### ICIR vs Calibration Metrics

| Reviewer | Position |
|----------|----------|
| Ava | ICIR for M5/M15 + live monitoring |
| Sora | Brier score + calibration first, ICIR secondary |
| Kaito | No strong opinion |
| Rei | No strong opinion |

**Resolution: Sora is right.** Add Brier score + calibration curve before ICIR. For binary signal systems, calibration (does 70% confidence actually win 70% of the time?) is more directly actionable than ICIR. Sequence:

1. Calibration + Brier score (1 day, works on existing data)
2. DSR gate (1 day, works on existing data)
3. ICIR live monitor (defer to Phase 10, needs more windows)

### DSR Code: Not Production-Ready

Kaito found 5 blocker-level defects in the research doc's Python sketch:
1. `min_windows_passed=5` default rejects all 9 streams silently (code uses 2)
2. `n_independent_trials=30` should be 160 (all evaluations, not per-strategy)
3. Annualization factor hard-coded to H1 (wrong for M5, H4, D1)
4. `n_obs` semantics mismatched (per-trade vs per-window)
5. Skewness/kurtosis defaulted to normal (real FX is left-skewed, fat-tailed)

**Resolution:** Fix all 5 defects before implementing. ~2 hours of work, not 1 day. Use real skewness/kurtosis from our trade data. Derive annualization from bar period. Set defaults to match production code (min_windows=3, n_trials=160).

### Data Scope: 2011 vs 2015 Start

| Reviewer | Start Year |
|----------|-----------|
| Ava | 2011 (12 years) |
| Rei | 2015 (8 years, avoids pre-2015 regime issues) |

**Resolution: 2015 start (Rei's position).** 8 years still satisfies MinBTL for 30 trials (needs 7-15). Avoids 2008-2014 regime shift complications (CHF unpegging, EU debt crisis). Cleaner data quality. Can extend backward later if needed.

---

## Revised Phase Plan

### Quick Wins (do now, no dependencies)
1. **Fix DSR code defects** (2 hours) → annotate 9 SRMR+ streams with DSR p-values
2. **Fix `min_windows_passed` discrepancy** in `go_nogo_criteria.py` (30 min)
3. **Add calibration + Brier score** to WF evaluation (1 day)

### Phase 3 (continued, parallel — unblocked)
- Continue strategy validation on existing data/infrastructure
- Apply DSR tier-ranking to 9 SRMR+ streams (Tier A/B/C)
- Paper-trade all 9, sized by tier
- Move to next strategy (momentum/sr_breakout) when Craig approves

### Phase 8: DuckDB Analytics Setup (3-4 days)
- 8a: DuckDB spike — import 21M M1 bars, validate CSV parity, benchmark (1 day)
- 8b: Schema design (bars, symbols, WF results) + migration of existing CSV (1-2 days)
- 8c: `DbDataLoader` class with same `list[Bar]` interface (1 day)
- SQLite untouched. Optuna studies stay SQLite. Live ticks → Parquet.

### Phase 9: Dukascopy Data (2-3 days, parallel with Phase 8)
- Download M1 bars 2015-2023 for 4 pairs (automated, chunked)
- Data QA: gap detection, regime flags, cross-validate against cTrader
- Import to DuckDB
- Build timeframe synthesis (M1 → M5, M10, M15, M30, H1)

### Phase 10: Testing Pipeline Upgrade (3-4 days, after 8+9)
- Switch data_loader to DuckDB-backed (with CSV fallback)
- Add ICIR for M5/M15 (30 WF windows)
- Integrate DSR gate into Optuna+WF pipeline
- Add live ICIR monitor to forward test
- Add cohort dashboard for 160 evaluations

### Phase 11: Re-validation (after Phase 10)
- Re-run SRMR+ on 8-year dataset with 30 WF windows
- Re-evaluate all 10 strategies
- Portfolio correlation analysis
- Council review of final results

---

## Tier Ranking for 9 SRMR+ Streams (to do this week)

Once DSR is fixed and applied, rank streams into:
- **Tier A (deploy-grade):** Top 3-4 by DSR p-value + per-window consistency
- **Tier B (paper-trade + monitor):** Middle 3-4
- **Tier C (archive unless revival):** Bottom 1-2

FTMO entry uses Tier A only, sized to assume 1-2 are false positives.

---

## Confidence Update

- **Pivot direction correct:** 0.90 (all reviewers agree)
- **DSR quick win delivers value this week:** 0.85
- **DuckDB + Parquet approach works:** 0.80 (no concurrency issue, proven pattern)
- **Dukascopy 2015-2023 data usable:** 0.80 (with QA spec)
- **Phase 3 continues unblocked:** 0.85 (Rei's key pushback adopted)
- **Overall quest completes in reasonable timeline:** 0.70 (was 0.55 before decoupling)
