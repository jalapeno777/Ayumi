# Alive — last refreshed 2026-07-22 21:58 EDT

## Active threads (Tsubaki/Mei/etc should read first)

1. **Strategy factory sprint (4h, Jul 22 17:38-21:55)** — done. LBO validated, 4 bugs fixed, gate loosening study re-run with corrected cache. See `docs/research/strategy-profiles/consolidated_findings_2026-07-22.md`.

2. **Forward test status** — was running 4-strategy gated blend; LBO + SRMR+ symbol fix wired into `scripts/launch_blend_forward_test.py` but live test process not confirmed alive.

3. **USDJPY harvest** — background process, was at Feb 2023 last check. May have completed or stalled.

## Open cards (Jul 22)

- 7318d89c: [DEBT] Re-validate 4-strategy blend against corrected cache [HIGH]
- 3febcb74: [TODO] Walk-forward validate LBO + 5-strategy blend [HIGH]
- a96a1c8f: [DEBT] Fix position-management model in run_blend_5strat.py [HIGH]
- 08aa128a: [TODO] Rerun SRMR+ confidence-gate test [NORMAL]
- f538fff0: [TODO] Profile USDJPY regime when harvest completes [NORMAL]
- 912e4e08: [DEBT] Audit codebase for other 60-bar precompute bugs [NORMAL]
- ec10b532: [DEBT] Wire daily-loss budget + FTMO trailing DD guard [HIGH]
- 5e78aa5e: [DEBT] Single-strategy concentration risk (LBO addresses, awaiting walk-forward)

## Decisions made

- LBO is a valid edge; recommended gate ADX[15,30] + LONDON session
- Regime gates are load-bearing — don't loosen SRMR+ beyond QUIET
- 250/day FTMO target is unrealistic; realistic is 50-150 trades/yr
- Original 4-strategy blend PF=1.74 needs re-validation against corrected cache

## Things I want to remember

- The cache bug (60-bar window) was silent — same pattern likely exists elsewhere
- pandas Series `[-1]` is label-based (silent failure mode)
- `SRMRPlusConfig.symbol` defaults to None and crashes silently on evaluate
- Craig wants me to keep working autonomously when given the green light
- "single strategy volume is fine if it's strong; blend is what needs volume"
