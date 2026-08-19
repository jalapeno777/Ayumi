# Council Consultation Record — Fresh Review of Roadmap v5

**Date:** 2026-08-08 UTC  
**Mode:** Advisory, read-only; no implementation performed

| Reviewer | Confidence | Verdict |
|---|---:|---|
| Kaito | 93% | Proceed with changes; not Ava-ready |
| Nora | Unavailable in this fresh pass | Not cleared |
| Mika | Unavailable in this fresh pass | Not cleared |
| Emi | Unavailable: requested `low`, model supports `adaptive` | Not cleared |

## Findings incorporated into v6

- Add quarterly post-phase drift checks with explicit regression statuses and reopen behavior.
- Assign ownership and approval/change control to the protected-scope manifest.
- Define replay determinism and a Craig-approved fallback when five agent-turn replays are infeasible.
- Add ongoing ledger self-budget checks and a tripwire that pauses collection when budget is exceeded.

## Disposition

The strict 96% per-reviewer gate was not met. Ava/main was not consulted. Unavailable reviewers are explicitly recorded; no confidence was inferred for them. The v6 roadmap incorporates the valid Kaito findings and remains documentation-only.
