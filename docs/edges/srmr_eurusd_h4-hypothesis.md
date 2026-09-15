# Hypothesis — srmr_eurusd_h4 (Phase 0.2 re-validation)

Question: Does stream srmr_eurusd_h4 with its 2026-07-08 Optuna params still pass >=3/5 calendar-anchored walk-forward windows with DSR>=0 on the freshest available data (through 2026-07-10/13), given the unresolved contradiction between the 2026-07-08 Optuna results and the 2026-08-01 blend-walkforward re-test?

Hypothesis: The Jul-08 Optuna PFs (3.6-7.2) were overfit to the training window; on data shifted forward, performance degrades (per Aug-01 evidence PF~1.59, WR~34%).

Falsification: >=3/5 windows passed AND DSR>=0 on freshest data.

Provenance: card d9ab5c61-ce2e-461e-9289-9ecafab8ccb0, plan Phase 0.2 (ayumi-strategy-engine-plan-2026-09-07.md), Satsuki 2026-09-07.
