# Ayumi Audit — 2026-09-15

*Evidence: live service + state files + roadmap rev 4 + 2026-09-08 Phase-1 plan + 2026-09-14 consolidation audit + tournament scorecards + git log (all read this session).*

## Where we actually are

**Stage:** Phase 1 LIVE (XAUUSD SRMR+ forward test on cTrader, D5 risk envelope) + Phase-2 tournament scaffold freshly merged (walking skeleton, 17-strategy sweep guard). Craig's 2026-09-11 pivot: **tournament-proven strategy quality before FTMO spend.**

## Live state (verified 15:18 UTC today)

| Metric | Value | Read |
|---|---|---|
| Balance | $9,942.71 (−0.57% from start) | Within envelope |
| Peak / FTMO DD | $10,262.45 / ~3.12% vs 10% cap | Watch, not alarm |
| Ticks / bars today | 125,119 / 70 — feed healthy | ✅ |
| Signals → trades today | **12 generated / 0 executed** | ⚠️ everything is being gated |
| Service restarts | counter=11 (last 2026-09-14 21:56 UTC) | ⚠️ flapping pattern |

## What's working

- Execution path proven: authenticated, broker-synced, live fills exist (288 trades telemetry, live_fills>0 per Sept 14 audit)
- Risk stack live: FTMOGuard, kill switch wired, D5 envelope, per-symbol 3-AT-RISK slots, sane_max loud-rejection counter
- Harness isolation incident (Sep 8) diagnosed and fixed with regression test (card d85c8d89, merged)
- Tournament skeleton merged; first full run (GBPUSD H1) executes end-to-end
- Test debt sprint discipline is holding (targeted scoping, harness boundary guards)

## What's weak (ranked by risk)

1. **Zero trades despite 12 signals today** — the confidence/gate stack is rejecting everything. SRMR+ alone at QUIET-only regime gating + confidence floor may be over-filtered. If this persists a week, the "1 week live under D5 → gate-loosening decision" (due ~Sep 15!) has nothing to evaluate.
2. **Tournament first result is damning**: best-ranked strategy on GBPUSD H1 is SRMR+ at **−0.59% return, 11.9% max DD, 14 total DD breaches**. That fails FTMO sim outright. The 5x-rejected candidates behind it are worse. This confirms the pivot: no tournament-proven edge exists yet on this pair.
3. **Service restart counter 11** — needs a look at WHY (circuit breaker on no ticks? restart loop?). Not investigated this session (journalctl permissions).
4. **Phase 1D never closed**: 5-strategy blend position-management model mismatch unresolved; blend backtest PF=1.74 suspect since the Jul 22 cache fix. The plan the live run rests on was never re-validated post-fix.
5. **USDJPY still has no data** (target pair, roadmap 0.1); GBPUSD cost runs parked; OOS trade exports parked.
6. **ML confidence layer is dead code on the live path** — correct per consolidation audit, but roadmap 1C.4 (wire to blend driver) is the un-executed bet that was supposed to fix signal quality.

## Next steps — recommended order

1. **Diagnose the zero-fill day (today).** Pull the signal→rejection log for today's 12 signals; classify rejections (confidence floor? regime gate? session gate?). One card, high priority. This is the cheapest, highest-information move.
2. **Make the Sep-15 gate decision explicit.** The "1 week under D5" checkpoint is due NOW. Options: (a) extend D5 a week with loosened gates per diagnosis, (b) keep live running as telemetry-only and shift energy to tournament. Recommend (b)-leaning hybrid: live stays as execution proving ground; tournament becomes the quality gate.
3. **Tournament matrix run (the real Phase 2).** Extend the skeleton to the full XAUUSD + GBPUSD × {M15,H1} × 17-strategy matrix with realistic FTMO costs. Current evidence says no edge on GBPUSD H1 — we need breadth to find where edges actually live. Compute target: ava-worker (per Sep 14 roadmap note).
4. **Restart-flap investigation** — small card: why 11 restarts; add restart-reason to health JSON.
5. **Close Phase 1D blend reconciliation** (card e7b2a23a) so the blend numbers that justify any future multi-strategy live config are trustworthy.
6. **USDJPY data download** (roadmap 0.1) — cheap, unblocks a target pair for tournament diversity. Can run in background on ava-worker.
7. **Then, only after tournament produces a passing blend**: wire ML confidence learner (1C.4) and re-run Phase 3 demo validation → FTMO.

## What NOT to do yet

- Don't buy the FTMO account. Tournament evidence says we'd fail it today.
- Don't loosen regime gates on live SRMR+ before the rejection diagnosis — QUIET-only gating is load-bearing (Jul 22 finding).
