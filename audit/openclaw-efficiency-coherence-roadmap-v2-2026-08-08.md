# OpenClaw Efficiency and Coherence Roadmap v2

**Status:** Planning and documentation only  
**Implementation authorization:** None  
**Date:** 2026-08-08 UTC  
**Authority root:** Ava = OpenClaw agent ID `main`  
**Source inputs:** Read-only audit, Ava's review, and recent council evidence from Nora, Kaito, Mika, Liora, and Emi

## Objective

Improve efficiency, safety, observability, and coherence across the OpenClaw organization while preserving:

- Ava/`main` at the head of the agent hierarchy.
- All current agent responsibilities, ongoing tasks, development workflows, and pipeline access.
- Memory, data, personality, continuity, and constitutional infrastructure.
- Existing BQES, workboard, delegation, backup, and delivery workflows unless a later approved change proves compatibility.

This document is a roadmap only. It does not authorize implementation, configuration changes, agent adjustments, cron changes, skill retirement, feature enablement, or bootstrap edits.

## Council synthesis incorporated

Recent council evidence converges on five planning corrections:

1. **Data integrity precedes optimization.** The behaviors registry and activation log disagree; the agency pipeline has a long silence; curiosity provenance is unknown; and desire evidence is thin relative to signal volume. These sources cannot safely serve as efficiency or identity baselines until reconciled.
2. **Instruction-only governance is fragile.** New process rules should be classified as mechanical, hybrid, or instruction-only. High-leverage gates should use existing Lobster, workboard, or runtime primitives where practical.
3. **Capacity must be explicit.** New monitoring and governance jobs need an owner, schedule slot, expected runtime/cost, concurrency impact, and fallback. Historical cron congestion and dropped-message evidence make unbounded monitoring unsafe.
4. **Continuity and identity need independent verification.** Stable files or large data volumes do not prove that the active behavioral or memory source is correct. Protected-file hashes, parse checks, backup manifests, and restore tests are required before any implementation phase.
5. **High-impact agents are last.** Satsuki or Kaori are potential canaries; Reina is high-impact because of delegation and workboard authority; Ava/`main` is last because it owns orchestration and the largest scheduler concentration.

These findings are advisory, not decision authority. They do not replace Craig approval or Ava/Sakura co-review for protected material.

## Confidence gate

The roadmap is not implementation-ready until all of the following are evidenced:

- Council has reviewed this exact roadmap revision using the required Nora-first sequence.
- Ava has reviewed the post-council revision and explicitly agrees with the sequencing, protections, and success criteria.
- Council synthesis and Ava's review each report confidence of at least 96%.
- A workspace/configuration/agent-state backup exists with manifest and checksums.
- An isolated restore test proves that memory, workboard, pipelines, agent state, and protected files remain readable and intact.
- Current responsibilities and active work are inventoried, with no uncovered owner or pipeline dependency.
- The hierarchy remains Ava/`main` → delegated agents; no authority redistribution is implied.
- No unresolved data-integrity issue is being used as a baseline for an agent or efficiency decision.

If any condition fails, the roadmap remains documentation-only.

## Ordered roadmap

### Phase 0 — Evidence integrity and preservation gate

Read-only planning targets:

- Reconcile behaviors registry versus activation log.
- Verify agency pipeline freshness, ownership, and routing.
- Classify curiosity provenance and desire evidence quality.
- Inventory current tasks, scheduled responsibilities, pipeline owners, and active agent dependencies.
- Define protected-file hash and parse checks without changing protected files.
- Define backup scope and isolated restore procedure for later approval.

Exit criteria:

- Every baseline dataset is classified clean, stale, broken, biased, or unknown.
- No identity, personality, or efficiency claim relies on a known-bad source.
- Current responsibilities have explicit owners or are marked unknown.

### Phase 1 — Shared scheduler and impact ledger

Design a read-only ledger joining:

- OpenClaw cron jobs.
- User crontab.
- `/etc/cron.d` and systemd services/timers.
- Command paths, output sinks, owners, schedule types, and execution kinds.
- Actual agent-turn versus command-only execution.
- Duration, retries, failure state, delivery state, concurrency, and token/cost data where already available.

The ledger must distinguish scheduler ownership from actual execution. The 149 jobs assigned to `main` must not be treated as 149 model-backed Ava sessions without evidence.

Exit criteria:

- Two snapshots reconcile all known scheduler layers.
- Unattributed jobs remain explicitly unattributed.
- Measurement overhead is bounded and sensitive payloads are excluded.
- Cost, failure, and contention metrics are available before redistribution is considered.

### Phase 2 — Sakura outbound safety control

Planning scope:

- Verify Sakura's effective runtime tool policy, including indirect delegation paths.
- Preserve Sakura's file-based outbox workflow.
- Design a deny-only guard for prohibited direct delivery to Ava/Craig.
- Define redacted audit events for blocked attempts.

No Sakura identity, personality, or domain-procedure prose is changed in this roadmap. Any later runtime guard requires Sakura/Ava review and Craig approval.

Required tests:

- Direct prohibited delivery is blocked before dispatch.
- Outbox writes remain allowed.
- Approved non-Craig operational paths remain unaffected.
- No message content is written to the guard telemetry.

### Phase 3 — Low-impact canary adjustments

Candidate order: Satsuki first, Kaori second, one agent at a time.

Each canary requires:

- Baseline execution and responsibility inventory.
- One narrowly scoped, reversible runtime or workflow adjustment.
- Targeted tests and shadow comparison.
- Observation window covering normal and scheduled duties.
- Independent verification of task completion, latency, failures, tool policy, memory continuity, and pipeline access.
- Immediate rollback plan.

Canary status does not imply that either agent is expendable. Their identity and current duties remain protected.

### Phase 4 — Skill activation and allowlist audit

Classify installed skills as active, indirectly used, rare-but-critical, experimental, stale, deprecated, or orphaned. Do not infer deletion from dormancy alone.

Move per-agent skill allowlists into the early safety boundary for any new skill load. Validate known callers and preserve a registry-only rollback. Skill files are not deleted as part of this roadmap.

### Phase 5 — Reina review

Only after Phases 0–4 pass, assess narrowly scoped Reina changes. Reina's delegation, workboard, BQES, and scheduled duties require dedicated regression tests and council review from the governance and systems lenses.

No changes may reduce Reina's current execution responsibilities or break routing to existing workers.

### Phase 6 — Ava/`main` review

Ava/`main` is the final target. Only changes already proven on shared infrastructure or lower-impact canaries may be considered.

Required evidence includes:

- No loss of hierarchy or delegation authority.
- No regression in ongoing development, BQES, workboard, memory, delivery, or backup workflows.
- No protected-file modification.
- Before/after cost, contention, failure, and continuity metrics.
- Craig approval and Ava/Sakura co-review for any identity-adjacent effect.

### Phase 7 — Optional scheduler redistribution

Redistribution is deferred until the ledger demonstrates measurable cost, contention, failure concentration, or ownership risk. Begin with command-only jobs and preserve schedule, permissions, outputs, context, and rollback mapping. Agent-turn and identity/relationship jobs require a higher review tier.

## Risk order and controls

| Rank | Risk | Required control before consideration |
|---:|---|---|
| 1 | Sakura outbound leakage | Effective-policy audit, deny-only guard design, blocked/allowed tests, redacted logging |
| 2 | Bad baselines from divergent data systems | Phase 0 reconciliation and source-quality labels |
| 3 | Backup that exists but cannot restore | Manifest, checksums, isolated restore, protected-file comparison |
| 4 | Cron/telemetry congestion | Capacity budget, bounded overhead, schedule ownership, concurrency measurement |
| 5 | Low-impact canary regression | One-agent/one-change rule, shadow period, independent verification, rollback |
| 6 | Reina workflow disruption | Delegation/workboard/BQES regression suite and governance review |
| 7 | Ava/`main` orchestration or identity impact | Final-stage-only policy, no protected edits, Craig approval, Ava/Sakura co-review |
| 8 | Incorrect skill retirement | Activation/dependency classification and registry-only rollback |
| 9 | Premature cron redistribution | Evidence threshold from ledger and command-only-first rollout |

## Non-negotiable invariants

- Ava/`main` remains the organizational authority root.
- No agent deletion, merge, demotion, or authority transfer.
- No current responsibility is removed without an explicit replacement owner and verified handoff.
- No memory, data, personality, continuity, or constitutional material is deleted, compressed, or rewritten.
- No BQES, workboard, delegation, backup, or pipeline gate is bypassed.
- No feature is re-enabled solely to improve audit coverage.
- No implementation begins while the 96% confidence and Ava-alignment gate is unmet.

## Roadmap-only acceptance checklist

- [ ] Fresh council assessment completed for this roadmap revision.
- [ ] Ava reviewed the post-council revision.
- [ ] Council confidence ≥96%.
- [ ] Ava confidence ≥96%.
- [ ] Data-integrity reconciliation plan complete.
- [ ] Backup and isolated restore plan complete.
- [ ] Scheduler capacity and impact schema complete.
- [ ] Responsibility/ongoing-task coverage matrix complete.
- [ ] Protected Ava/Sakura register unchanged.
- [ ] No implementation authorized by this document.
