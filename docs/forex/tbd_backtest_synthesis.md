# TBD Forex Backtest Synthesis — Q1-Q7 Final Results

**Date:** 2026-04-10
**Source Issues:** AYUAA-641 (parent), AYUAA-699 (this task)
**Data Sources:** `reports/backtest_q1_mw_formation.json`, AYUAA-647 (Q5), AYUAA-648 (Q7), issue comments

## Executive Summary

| Q | Test | Result | GO/NO-GO | Samples |
|---|------|--------|----------|---------|
| Q1 | M/W 3:1 R:R | 1.04% hit rate | **NO-GO** | 624 |
| Q2 | LOD/HOD stop rate | 57% SL, 71% intrabar spike | **NO-GO** | — |
| Q3 | Wednesday reversal | 22% reversal rate | **NO-GO** | — |
| Q4 | Friday gap | 12% gap freq, 91% level test | **PARTIAL** | — |
| Q5 | Board consolidation | 94% breakout >=4hr consolidation | **GO** | 20 |
| Q6 | DXY leading/lagging | 51% DXY lead, no edge | **NO-GO** | — |
| Q7 | Multi-session M/W | 68% WR multi vs 54% single | **GO** | 623 |

**Bottom line:** 2 GO (Q5, Q7), 1 PARTIAL (Q4), 4 NO-GO (Q1, Q2, Q3, Q6).

---

## GO Findings

### Q5: Consolidation Duration Filter — IMPLEMENT

**Finding:** Consolidations >=4 hours precede 94% profitable breakouts.

| Metric | Value |
|--------|-------|
| Optimal consolidation | >=4 hours |
| Profitable breakout rate | 94% |
| Sample size | 20 board meeting periods |
| Test period | 2025-10-01 to 2026-03-31 |

**Cross-reference:** Q7 shows multi-session M/W formations win 68% vs 54% single-session. Longer consolidations (multi-session) correlate with higher win rates, supporting Q5 finding.

**Implementation Spec:**
- **Entry rule:** Wait for >=4hr consolidation before M/W breakout entry
- **Data needed:** Session start/end timestamps, H1 candle data
- **Effort:** Low — filter addition to existing M/W detector

**Handoff: IMPLEMENT** → Child task [AYUAA-719](/AYUAA/issues/AYUAA-719) already created

---

### Q7: Multi-Session M/W Preference — IMPLEMENT

**Finding:** Multi-session M/W formations win 68% vs 54% for single-session.

| Metric | Value |
|--------|-------|
| Multi-session win rate | 68% |
| Single-session win rate | 54% |
| Multi-session frequency | 58% of formations |
| Avg sessions per formation | 2.3 |
| Sample size | 623 formations |
| Test period | 2020-01-01 to 2024-12-31 |

**Cross-reference:** Q5 confirms longer consolidations produce better outcomes. Multi-session M/Ws are simply the manifestation of longer consolidation periods.

**Implementation Spec:**
- **Entry rule:** Weight multi-session M/W signals higher (2:1 preference ratio)
- **Data needed:** Session boundary detection on H1 chart
- **Effort:** Low — add session_span attribute to M/W detector

**Handoff: IMPLEMENT** → Child task [AYUAA-720](/AYUAA/issues/AYUAA-720) already created

---

## NO-GO Findings

### Q1: M/W 3:1 R:R — REJECT (pending validation)

**Finding:** Only 1.04% of M/W formations hit 3:1 target.

| Metric | Value |
|--------|-------|
| 3:1 hit rate | 1.04% |
| Average R:R achieved | 0.677:1 |
| L1 hit rate | 59.07% |
| L2 hit rate | 2.76% |
| L3 hit rate | 1.04% |
| Stop loss rate | 37.13% |
| Sample size | 624 |
| Test period | 2023-01-01 to 2025-12-31 |

**Analysis:** L1 win rate is 59% but R:R collapses. Most wins are small (L1) vs the 3:1 target. The 3:1 R:R hypothesis is **not supported by data**.

**Handoff: REJECT** — 3:1 R:R not supported; recommend re-testing at 2:1 or 1.5:1

---

### Q2: LOD/HOD Stop Rate — SYSTEMIC FINDING (not a strategy reject)

**Finding:** 71% of stops are intrabar spikes through LOD/HOD, not level touches.

| Metric | Value |
|--------|-------|
| LOD/HOD stop rate | ~57% |
| Intrabar spike rate | 71% |
| Implication | Stops get spiked through before reversing |

**Strategic Implication:** This is a **systemic finding**, not a strategy reject. The stop buffer parameter needs adjustment.

**Cross-reference:** Q5/Q7 GO findings should incorporate 8-pip minimum stop buffer to avoid intrabar spikes.

**Implementation Spec:**
- **Stop rule:** Place stops minimum 8 pips beyond LOD/HOD
- **Rationale:** 71% intrabar spike rate means level is often penetrated before reversal
- **Effort:** Low — parameter change

**Handoff: IMPLEMENT** → Child task [AYUAA-721](/AYUAA/issues/AYUAA-721) already created

---

### Q3: Wednesday Reversal — REJECT

**Finding:** Only 22% Wednesday reversal rate, well below 50% threshold.

**Handoff: REJECT** — Wednesday reversal is not a reliable edge

---

### Q6: DXY Leading/Lagging — REJECT

**Finding:** 51% DXY lead, no usable edge.

**Handoff: REJECT** — DXY timing filter provides no statistical advantage

---

## PARTIAL Finding

### Q4: Friday Gap — DEFER

**Finding:** 12% gap frequency but 91% level test rate.

| Metric | Value |
|--------|-------|
| Gap frequency | 12% |
| Level test rate | 91% |

**Analysis:** Low sample frequency (12%) makes this difficult to trade systematically. When gaps occur, price does return to test the level.

**Handoff: DEFER** — Too infrequent for systematic trading; may revisit with larger dataset or longer timeframe

---

## Cross-Reference Analysis

### Q2 Intrabar Spike → Q5/Q7 Interaction
Q2's 71% intrabar spike rate is a **key systemic parameter**. It affects all GO strategies:
- Q5 consolidation entries need wider stop buffer
- Q7 multi-session M/W entries need wider stop buffer

**Recommendation:** All forward test parameter sweeps (AYUAA-491, AYUAA-495) should include 8-pip minimum stop buffer as baseline.

### Q1 vs Q7 — Same Pattern, Different Timeframes
Q1 tested M/W 3:1 R:R on all formations (single + multi-session combined). Result: NO-GO.
Q7 separated by session count: multi-session WR 68%, single-session WR 54%.

**Insight:** The 14-point differential suggests session count is a confounder. Q1's aggregate failure may mask the multi-session sub-population outperformance.

**Action:** Re-test Q1 hypothesis (M/W formations with 3:1 R:R) on **multi-session only** subset. This could revive the 3:1 R:R hypothesis for a filtered sub-population.

---

## Strategy Recommendations Summary

| Decision | Strategy | Rationale |
|----------|----------|-----------|
| **IMPLEMENT** | Consolidation >=4hr filter | Q5: 94% breakout rate |
| **IMPLEMENT** | Multi-session M/W preference | Q7: 68% vs 54% WR |
| **IMPLEMENT** | 8-pip LOD/HOD stop buffer | Q2: 71% intrabar spike |
| **REJECT** | M/W 3:1 R:R (all formations) | Q1: 1.04% hit rate |
| **REJECT** | Wednesday reversal | Q3: 22% reversal rate |
| **REJECT** | DXY timing filter | Q6: no edge |
| **DEFER** | Friday gap strategy | Q4: 12% frequency too low |
| **EXPLORE** | 3:1 R:R on multi-session only | Q1/Q7 cross-reference |

---

## Forward Test Pipeline Impact

**GO findings (Q5, Q7) should feed into:**
- AYUAA-617: Forward test success criteria
- AYUAA-491: Parameter sweep configs
- AYUAA-495: Forward test design

**Key parameters for FTMO forward test:**
1. Require >=4hr consolidation before entry
2. Prefer multi-session M/W formations
3. 8-pip minimum stop buffer beyond LOD/HOD

---

## Appendix: Data Sources

| Source | File/Issue | Status |
|--------|------------|--------|
| Q1 results | `reports/backtest_q1_mw_formation.json` | Final |
| Q5 results | AYUAA-647 | Done |
| Q7 results | AYUAA-648 | Done |
| Q2 results | Stash (AYUAA-709 context) | Done |
| Q3-NO-GO | Issue comment AYUAA-699 | Confirmed |
| Q4-Partial | Issue comment AYUAA-699 | Confirmed |
| Q6-NO-GO | Issue comment AYUAA-699 | Confirmed |