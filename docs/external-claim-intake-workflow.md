# External Claim Intake & Reference-Feature Workflow

**Origin:** sma-research sprint 2026-09-11 (SMA "outfit" falsification — full record: `/root/.openclaw/workspace/projects/sma-research/docs/00-INDEX.md`)
**Skill:** `~/.openclaw/workspace/skills/falsify-trading-claims/SKILL.md` (canonical procedure — read before first use)

## Purpose

Standardize how external trading claims (influencers, repos, signal sources, "magic" parameter sets) enter Ayumi/Cabal evaluation, and how the one validated feature family from the 2026-09-11 sprint (reference-interaction features) is staged for adoption.

## Part 1 — Claim intake gate (any new external claim)

1. **No claim influences Ayumi/Cabal without passing the falsification skill.** Pre-registration → matched controls (±neighbors, random sets, canonical baselines) → FDR correction → stability → pre-committed kill/promotion criteria.
2. **Internal consistency check first** (cheapest kill): does the source actually use its own claimed parameters across its corpus?
3. **Test on the claim's native habitat** — instruments and timeframes the source actually trades — or the null is structural. (Ayumi note: FX leg uses cTrader historical depth; intraday equity claims used yfinance 60d 5m first pass, paid source only if escalation triggers.)
4. **Verdict by pre-registered criteria only.** Survivors enter at OBSERVE tier; the OBSERVE→RESEARCH→PAPER→CANARY→AUTHORIZED ladder requires walk-forward gains on data independent of the source's own examples.
5. Hard rule (Craig, standing): nothing dismissed merely because unproven; nothing accepted as fact without strenuous testing. Confidence-modifier is the default landing zone — with a documented promotion path, never a permanent ceiling.

## Part 2 — Reference-interaction features (sma-research survivors, staged)

Validated findings worth staging as features (all period-agnostic — integers are NOT privileged):

- **Multi-MA confluence geometry:** ≥3 MAs within 1 ATR of price carry measurable forward drift (+0.3–0.8% at 10–20 bars daily; random-period clusters match — the clustering, not the periods, matters).
- **Canonical-MA attention:** 20/50/100/200 show the strongest, most consistent reactions (self-fulfilling attention; literature-backed). Reference maps should use canonical periods by default.
- **Invalidation-quality scoring:** reference-failure stop definition (close-through + failed reclaim) with microstructure floor `max(reference_break, spread_buffer, k·ATR)`; feeds position sizing. Directly relevant to FTMO 3%/10% DD constraints.
- **SMA-ladder targets:** next-reference ladders instead of fixed TP where reaction quality supports continuation.

**Integration posture (council-approved 2026-09-11):** confluence/reference features are confidence **modulators, never initiators**. `P(final) = calibrator(P(base), reference_features)` — measurable incremental lift required before any influence beyond OBSERVE.

## Part 3 — Deferred branches

- Adoption-effect hypothesis (attention-flow making claimed parameters self-fulfilling): open only with pre-registered cohort design + attention covariates; treat as exploratory.
- Event-engine promotion: WP2/WP5 scripts (workspace `projects/sma-research/scripts/`) are the seed; promote to an Ayumi module only after 60 days of observation value demonstrated.
