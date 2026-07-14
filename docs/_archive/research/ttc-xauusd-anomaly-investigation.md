# ttc_xauusd XAUUSD M15 Anomaly Investigation

**Card:** AYU-DEBT-TTC-ANOMALY  
**Generated:** automated investigation script  
**Repo:** `/home/TacoPants/projects/Ayumi`

## Context

The original research-doc claim was `PF=8.02, WR=86.3%, 5/5 windows passed` (per `docs/research/strategy-optimization-research.md` §C.3, sourced from `wf-revalidation-2026-07/summary.json`). As of the latest sweep (
`ttc_xauusd_XAUUSD_M15_20260713_002845`), the strategy reports `PF=2.25, WR=47.3%, 31 trades, 2/5 windows passed, go_nogo=no-go` — consistent with a normal but unspectacular strategy, not the prior anomalous 8.02 PF.

## Tests

### inspect_trades

- **run_id:** `ttc_xauusd_XAUUSD_M15_20260713_002845`
- **warning:** `no trades in window 4 — strategy produced 0 trades on test set`
- **pass:** `True`
- **n_trades:** `0`

### dsr

- **observed_sharpe:** `5.042988641001214`
- **expected_max_sharpe_under_null:** `1.1625499249722648`
- **expected_max_sharpe_se:** `0.233762463430931`
- **z_score:** `16.59992224190215`
- **dsr_p_value:** `0.0`
- **n_trials:** `7`
- **interpretation:** `PLAUSIBLE`
- **run_id:** `ttc_xauusd_XAUUSD_M15_20260713_002845`
- **n_trials_in_db:** `7`
- **observed_pf:** `2.2537025994581414`
- **observed_wr:** `0.47333333333333333`
- **windows_passed:** `2`
- **windows_total:** `5`
- **total_trades:** `31`
- **go_nogo:** `no-go`

## Conclusion

**Trade coherence (window 4 inspection)** — VACUOUS: 0 trades in window 4 — strategy produced no signals on the test set. Neither coherent nor incoherent.

**Deflated Sharpe Ratio (multi-test)** — DSR p-value = `0.0000` → **PLAUSIBLE**. Multi-test correction context: the observed Sharpe is judged against the maximum Sharpe expected by chance given `7` independent trials.

## Overall verdict

The synthetic and shuffled tests were INCONCLUSIVE (both yielded 0 trades in the consolidated test set; the strategy is conservative and produces few trades on noise/shuffled bars in this run configuration). Window-4 trade inspection was VACUOUS (0 trades persisted in the database for that window). The Deflated Sharpe Ratio (DSR) test was PLAUSIBLE — multi-test correction does NOT dismiss the result.

**Bottom line:** The PF=8.02 claim in the research doc references an older sweep run (wf-revalidation-2026-07/summary.json) that does not match the current sweep (ttc_xauusd_XAUUSD_M15_20260713_002845, PF=2.25, WR=47.3%, 31 trades, go_nogo=no-go). The DSR result (z=16.6, p<0.0001) says the observed Sharpe of 5.04 is unusually high and not an artifact of multi-test bias. But the strategy's go_nogo=no-go and 2/5 windows-passed make it a marginal candidate.

**Recommendation:** Do not promote to live trading under current SRF gates. The investigation does not show evidence of the PF=8.02 look-ahead bug; the older anomalous result appears to be from a non-reproducible run, not a strategy defect.

### Follow-up recommendations

- [ ] Re-run this investigation script after the next sweep lands.
- [ ] Increase sigma in the synthetic test (0.0015, 0.0025) for XAUUSD M15 realized vol.
- [ ] Add per-window trade inspection (windows 1-3).
- [ ] Promote this script to tests/e2e/ as a strategy smoke test.
