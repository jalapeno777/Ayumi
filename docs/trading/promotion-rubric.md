# Promotion Rule Rubric — Second-Strategy Selection

Companion to `docs/trading/active-blade.md` § Promotion Rule (card 5d7c068b,
child of 5aeb2d40). Gate: the active edge must first complete **1 clean
live/paper quarter**, validated by `scripts/promotion_validator.py --quarter <qid>`.
Only a quarter that passes all 4 clean-receipt criteria (order fill integrity,
slippage distribution, regime hit rate ≥70%, no sev-1/sev-2 traceable to the
edge) opens promotion. A single failed criterion closes the quarter — no
partial credit at the gate.

## Scoring (validator output)

Per-criterion weights: order fill integrity 0.30, slippage 0.25, regime hit
rate 0.25, incident cleanliness 0.20. The gate is all-or-nothing; the weighted
score is informational for the triage packet, not a bypass.

## Candidate ranking (among validator-passing Hold-class strategies)

Ranked on walk-forward evidence from `docs/trading/parked-strategies.md` Hold
list, scored 0–5 per dimension (weights in parentheses):

1. **Walk-forward PF stability** (0.30) — median PF across windows; variance penalty.
2. **Max drawdown** (0.25) — DD ≤ -5% per exit criteria; deeper DD caps the score.
3. **Noise-floor robustness** (0.25) — ≥30 live/paper trades clean under the same 30-trade guard.
4. **Correlation to active edge** (0.20) — lower correlation to the active blade scores higher (diversification).

## Tiebreaker order

1. Higher walk-forward PF stability score.
2. Lower max drawdown.
3. Lower correlation to active edge.
4. Earlier date added to the Hold list (longest-parked wins ties — freshness bias is explicitly rejected).
5. If still tied: no promotion this quarter; hold the slot.

## Himari triage input format

Triage packet posted to the promotion card before Craig review, one block per
candidate:

```
candidate: <strategy_id>
hold_list_score: <0-5>
validator_quarter: <qid>            # gate result for the ACTIVE edge, not the candidate
wf_pf: {windows: [..], median: .., min: ..}
max_dd_pct: <negative percent>
noise_trades_clean: <n>
corr_to_active_edge: <-1..1>
score_breakdown: {pf: .., dd: .., noise: .., corr: .., total: ..}
```

Himari verifies each number against `parked-strategies.md` and walk-forward
output before the packet reaches Craig.

## Craig approval gate

- Promotion requires Craig's explicit approval on the card. No auto-promotion,
  no promotion by silence or timeout.
- Craig may reject the top-ranked candidate or the entire cohort; a rejection
  re-arms the rule for the next clean quarter.
- Exit criteria and early-evaluation triggers (pip_value fix + ≥0.3 PF edge)
  remain governed by `active-blade.md` § Exit Criteria, not this rubric.
