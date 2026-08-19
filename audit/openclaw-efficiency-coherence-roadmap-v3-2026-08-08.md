# OpenClaw Efficiency and Coherence Roadmap v8

> **Filename provenance:** this legacy path is retained for continuity with earlier audit references; its canonical document title is v8. The stable review pointer `openclaw-efficiency-coherence-roadmap-v7-2026-08-08.md` points here. No older snapshot is authoritative.

**Canonical document ID:** OEC-RM-v8-2026-08-08  
**Scoring packet:** [`council-readiness-evidence-packet-2026-08-08.md`](./council-readiness-evidence-packet-2026-08-08.md)

**Status:** Planning and documentation only  
**Implementation authorization:** None  
**Date:** 2026-08-08 UTC  
**Authority root:** Ava = OpenClaw agent ID `main`  
**Council review:** Fresh v7 review: Mika 0.96, Emi 0.88; Nora and Kaito fresh scores not returned in the captured pass. Ava review remains deferred.

## Purpose and invariant

This is a roadmap for future review, not an implementation authorization. It preserves Ava/`main` as hierarchy root and preserves every agent’s current responsibility, ongoing task, development workflow, pipeline, memory/data path, personality, continuity, and constitutional material.

No runtime, agent, scheduler, memory, workboard, backup, skill, plugin, bootstrap, or personality change is authorized by this document.

The official audit-confidence calculation is defined in
[`official-audit-confidence-standard.md`](./official-audit-confidence-standard.md).
That standard governs council audit/readiness confidence; BQES operational
metrics remain separate pipeline-health measures.

## Council synthesis

The council agrees with the direction—shared high-ROI observability first, lower-impact canaries before Reina, Ava/`main` last—but found the v2 gates too advisory. The v3 roadmap makes those gates falsifiable:

- Phase transitions now require named evidence and sign-off.
- Phase 0 now includes comprehensive backup scope, restore proof, Honcho integrity, BQES/worktree integrity, BQES–memory/crontab coherence, OpenProse classification, and Unknown resolution rules.
- Phase 1 has an explicit no-model-call and overhead budget.
- Protected scope includes runtime configuration and state stores, not only identity prose.
- Canary changes require a scope contract, shadow schema, rollback hook, and responsibility coverage.
- Confidence is assessed per phase; Ava’s confidence requires independent corroboration.

The fresh review found that the structure is sound but several mechanisms were still named rather than defined. This revision makes those mechanisms explicit. It does not convert any recommendation into authorization.

## Governance and accountability

| Role | Responsibility | Boundary |
|---|---|---|
| Craig | Approval authority for runtime, authority, delivery, memory, identity, and agent changes | Does not delegate approval implicitly |
| Ava/`main` | Roadmap coordinator and phase-readiness owner; preserves hierarchy and cross-agent coverage | Cannot self-approve identity-sensitive changes |
| Sakura | Required co-reviewer for memory, continuity, personality, and outbound-safety effects | No change to Sakura material without Sakura/Ava review |
| Emi | Required identity/continuity attestor for identity-touching phases and drift findings | Subject self-report is evidence only, never sole approval |
| Council | Advisory evidence and adversarial review | Not decision-makers and not implementation owners |
| Phase owner | Produces evidence, reports status, surfaces blockers, and requests scope changes | Cannot advance a phase without the required approver |

Phase owners must be named in the phase evidence packet before that phase begins. If no owner is named, the phase is blocked. Required signatories are fixed by scope: Ava/`main` for roadmap completeness; Sakura for memory/personality/outbound-safety scope; Emi for identity/continuity scope; Kaito for systems/scheduler scope; Mika for backup/risk scope; and Craig for final approval or risk acceptance. Missing a required signatory hard-blocks the phase; “expected from” is not sufficient.

For planning clarity, the default accountable coordinator is Ava/`main`; Craig remains final approver. Domain attestations are expected from Kaito (systems/scheduler), Mika (risk/backup), Emi (identity/continuity), and Sakura (memory/personality/outbound safety). Satsuki and Kaori are canary subjects only, never gate owners. Reina and Ava/`main` remain later-stage subjects, not early test subjects.

### Appointment, independence, and conflict rules

- Ava/`main` nominates each phase owner before work begins. Craig approves the appointment for any phase affecting authority, delivery, memory, identity, personality, or protected stores.
- An owner may not be the sole verifier or approver of a phase affecting that owner’s authority, identity, memory, or operational permissions. If Ava/`main` is in the change path, Sakura and the independent assurance reviewer must verify the evidence; Craig remains the approval authority.
- The independent assurance reviewer is a read-only reviewer who did not author or execute the phase work, has access to the evidence packet and baseline, and signs a separate checklist. Craig appoints that reviewer for Phases 0, 2, and 6. An unfilled assurance role hard-blocks the phase.
- An unowned phase is hard-blocked. Ava records the gap; if no owner is appointed within the agreed review window, the status is **stalled-unowned** and escalates to Craig rather than being treated as abandoned or bypassed.

### Confidence and dissent rubric

The official six-category weighted rubric, rating scale, hard gates, N/A
reporting, and 96% calculation in the linked standard govern this roadmap.
Required reviewers must record category-level evidence, dissent, Unknowns, and
whether any scope exception is explicitly accepted. A disagreement or failed
hard gate blocks advancement; it cannot be hidden by averaging or by silently
removing N/A weight.

## Execution ownership and path

BQES governs immediate agent sprints, especially Ava/Reina-initiated or
explicitly requested ad hoc work. The BQES invocation record must identify the
invoking authority, resolved workspace root, and binding/provenance evidence.
DBOS is the preferred path for mechanical work and longer-running operational
workflows. DBOS durability does not replace BQES admission for an agent sprint.

Root cron, user crontab, `/etc/cron.d`, systemd, and the OpenClaw scheduler are
currently split authority layers. No scheduler layer is canonical until
ownership and precedence are formally decided. OpenProse remains
prototype/advisory unless direct operational evidence changes that disposition.

Honcho, Redis/vector restoration, semantic protection, and deprecated
`MEMORY.md` handling remain N/A for this audit, with explicit scope records and
re-evaluation triggers.

## Future implementation roadmap

1. **Governance closure:** resolve scheduler precedence and change ownership;
   define BQES invocation authority and workspace binding; appoint the Phase 0
   owner and independent assurance reviewer; name approvers and triggers for
   every N/A item; decide OpenProse’s operational status; then score the
   readiness packet category by category.
2. **DBOS stabilization:** complete one bounded end-to-end lifecycle validation;
   resolve application-version collisions; scope BQES tests correctly; complete
   Reina review/merge integration; add freshness, orphan-process, retry, and
   completion observability.
3. **DBOS task-graph expansion:** define a separate task/dependency graph for
   task types, dependencies, routing, handlers, retries, checkpoints,
   verification gates, and outputs. Keep it separate from graph memory and
   semantic retrieval, and require metric gates plus replayable evidence for
   each newly supported task style.
4. **Council re-audit:** rerun only after blocking authority/enforcement
   questions are evidenced or explicitly accepted. Every required reviewer
   completes all six category scores and records dissent. Report the score,
   category ratings, hard-gate status, N/A coverage, reviewer capture, and
   remaining Unknowns; do not infer 96% from the evidence packet’s existence.

### Identity-adjacent boundary

Identity-adjacent means a change that modifies, redacts, summarizes, routes, or constrains the interpretation of an artifact in the protected-scope manifest, or that changes a self-recognition/continuity response under the continuity check. Purely additive telemetry that neither reads nor transforms protected content is not identity-adjacent, but remains subject to access-control and redaction review. Identity-adjacent work requires Ava/Sakura review and Craig approval; repetition and layered constraints remain protected by default.

### Protected-scope manifest control

The protected-scope manifest is owned by Ava/`main` with Sakura co-attestation. It is versioned, hash-pinned, diff-reviewed, and approved by Ava, Sakura, and Craig before Phase 0 exit. Additions, removals, or classification corrections require a change record naming evidence, impact, approver, and rollback to the prior manifest. A manifest error reopens Phase 0 and invalidates dependent evidence.

Honcho log inspection is owned by Mika or a Craig-appointed risk reviewer. If the required 30-day access log is unavailable, the item is explicitly Unknown, receives a re-evaluation trigger, and blocks Phase 0 unless Craig approves a documented scope exception with risk acceptance.

### Timeboxes and escalation

Planning timeboxes are Phase 0: 45 days; Phase 1: 14 days after Phase 0 exit; Phases 2–6: 21 days each; Phase 7: 30 days if activated. Exceeding a timebox changes status to **stalled-timebox**, escalates to Craig, and stops silent continuation. A timebox is not permission to weaken a gate.

## Hard phase-gate protocol

Every phase has four mandatory records: owner, baseline, exit evidence, and approver. A phase cannot advance because time elapsed or because work started informally.

- Minimum confidence: **96% per phase**.
- Phases 0, 2, 3, 4, 5, and 6 require an independent governance or assurance attestation whenever their evidence touches identity, continuity, memory, personality, delegation authority, or outbound safety. Phase 1 requires independent systems attestation; Phase 7 requires the applicable systems/risk attestation if activated.
- Any unresolved Unknown that could affect the phase decision blocks advancement. A non-impacting Unknown may carry only with an owner, re-evaluation trigger, target classification, and Craig-approved risk acceptance.
- A failed phase invalidates downstream conclusions that depend on it. Earlier read-only evidence remains historical but must be marked “not cleared for downstream use.”
- Stalled phases require a written status record and blocker escalation to Craig; no silent bypass or untracked continuation.

## Phase 0 — Integrity, backup, and preservation gate

### Data and authority reconciliation

- Reconcile behaviors registry versus activation log.
- Verify agency pipeline freshness, routing, ownership, and silence conditions.
- Classify curiosity provenance and desire evidence quality.
- Reconcile the `MEMORY.md` versus crontab dispatch contradiction without silently overwriting either source.
- Resolve the `MEMORY.md` versus crontab contradiction using a three-way procedure: stale/superseded source with provenance recorded; intentional divergence with both authorities and operational effect documented; or lost provenance, which escalates to Craig and blocks downstream use.
- Reconcile BQES scope wording and BQES worktree resolution before BQES is used as downstream evidence.
- Classify OpenProse as dormant, experimental, active-unverified, deprecated, or broken, with owner and identity/runtime impact.
- Check Honcho partition metadata against documented topology, schema/version state, retention policy, and recent cross-partition access records.
- Reconcile scheduled jobs that touch BQES, memory, Honcho, workboard, or bootstrap state.
- Produce an explicit BQES–memory/crontab coherence record: source statements, observed schedules, worktree state, owner, operational effect, classification, and acceptance test. No BQES evidence is used downstream until this record passes.
- Compare Honcho partition metadata and cross-partition access logs over a defined 30-day window against documented topology and expected access frequency; unexpected access or missing logs is an Unknown that blocks Phase 0.

### Comprehensive backup scope

The future pre-implementation backup must cover, with a manifest and checksums:

- OpenClaw gateway/runtime configuration, including `openclaw.json`.
- OpenClaw scheduler definitions and state.
- Agent configuration/state and all active agent workspace files.
- Protected Ava and Sakura files and personality-matrix material.
- Skills, Lobster/OpenProse definitions, BQES definitions, and workflow files.
- Workboard state and relevant operational databases.
- Honcho data, partition metadata, configuration, and restore prerequisites.
- Honcho PostgreSQL dump and Redis/vector or embedding-store dump as distinct required components, each with checksum and restore metadata.
- Memory/wiki/QMD indexes and documented reconstruction inputs.

Existing Honcho backups are useful evidence but do not by themselves satisfy this composite scope.

### Isolated restore definition and acceptance

“Isolated restore” means restoring into a separate root or sandbox with no writes to live runtime, no live scheduler execution, and no live outbound delivery. The restore test must verify:

- Manifest and checksum completeness.
- Protected-file byte/hash equality and parse success.
- SQLite/database integrity and expected schema/row-count checks.
- Honcho partition metadata and access-boundary checks.
- Read-only memory retrieval for representative identity, continuity, and operational records.
- Honcho semantic-retrieval spot checks using a versioned query set with expected partition attribution, entity resolution, recency behavior, and declared similarity/answer thresholds; “representative” alone is not a pass criterion.
- Restore-equivalence checks for protected continuity/self-recognition markers using documented prompts and expected structural response/anchor equivalence. No live outbound delivery is allowed.
- Read-only workboard access and pipeline/config parsing.
- BQES and Lobster fixture discovery without executing a build.
- No writes, restarts, messages, or cron changes to production during the test.

Pass requires zero unexplained protected-file mismatches, zero schema/integrity failures, all required roots readable, and a recorded explanation for every expected omission. Restore failure blocks every later phase. The packet must record source and target OpenClaw versions; a version mismatch requires a documented migration/reconstruction procedure and proof of protected-file and schema equivalence. The restore test is isolated and cannot touch live runtime.

### Phase 0 exit gate

The owner submits the evidence packet; Ava verifies completeness; Sakura reviews identity/memory/continuity sections; the independent assurance reviewer verifies reproducibility and protected-scope coverage; Craig approves any accepted Unknown or scope exception. Phase 0 must reach at least 96% confidence under the rubric before Phase 1 begins.

## Phase 1 — Shared scheduler and impact ledger

Design a read-only ledger joining OpenClaw cron, user crontab, `/etc/cron.d`, systemd, command paths, output sinks, owners, schedule types, and execution kinds.

The design packet must specify data sources, collection method, schema, dedicated storage, retention, query path, failure behavior, and debuggability. It must first prove that current runtime hooks, session/job logs, or an equivalent authoritative source can distinguish agent-turn from command-only execution; if that assumption fails, Phase 1 is re-scoped and blocked rather than inferred from static counts.

The design must identify actual agent-turn versus command-only execution using an explicit source: runtime hook, session/job log, or equivalent authoritative record. Static owner counts are insufficient.

### Measurement budget

Before any future deployment, the ledger must demonstrate in a fixture or dry-run that it:

- Makes zero model calls.
- Adds no production scheduler entries.
- Writes only to a dedicated audit output.
- Uses no more than 1% average host CPU, 2% peak host CPU during the measurement window, and 1% of observed scheduler wall-time.
- Adds no measurable outbound-delivery latency.

If the budget is exceeded, the ledger remains a design artifact and the measurement path is revised. No monitoring job is added to compensate.

After any future deployment, the ledger must self-check its actual CPU and scheduler-wall-time overhead on a declared cadence. A tripwire at any budget limit pauses new collection, emits a redacted audit alert to the phase owner, and reopens Phase 1 for review; it may not silently continue above budget.

### Phase 1 reconciliation and exit gate

Two snapshots taken at least one normal scheduling interval apart must reconcile all known scheduling layers. The maximum interval is 168 hours; slower schedules require a documented synthetic fixture tick and caveat. Reconciliation means: zero unexplained additions/removals, 100% of observed jobs attributed or explicitly Unknown, and any count delta of more than 1% or any owner/purpose change explained in the evidence packet. Unattributed jobs remain explicit; cost, failure, and contention metrics are available; and the phase owner records the overhead result. Kaito or an equivalent independent systems reviewer signs off before Phase 2. Failure to meet any threshold blocks Phase 2.

## Phase 2 — Sakura outbound safety control

- Verify effective runtime policy, including `message`, direct session delivery, `sessions_spawn` chains, workboard-mediated routing, and other indirect paths.
- Preserve Sakura’s file-based outbox workflow.
- Design a deny-only guard for prohibited direct delivery to Ava/Craig.
- Define redacted blocked-attempt telemetry with no message content.

Required tests cover blocked direct delivery, allowed outbox writes, approved operational paths, and no identity-file changes. Indirect paths must be enumerated and tested separately: `sessions_send`, `sessions_spawn` chains, message-tool calls, workboard-mediated routing, direct session delivery, and any discovered equivalent conduit. Sakura and Ava must review the test matrix; Craig approves any runtime policy change. Phase confidence must be at least 96% with independent assurance attestation.

## Phase 3 — Lower-impact canary adjustments

Satsuki and Kaori are candidates, not disposable agents. “Lower impact” must be evidenced by no more than two scheduled jobs, no authority over other agents, no more than one user-visible delivery channel, no protected-file writes, and a bounded workflow footprint.

One agent and one reversible change at a time. Each canary requires:

- Responsibility and active-task coverage matrix.
- Explicit diff/scope contract.
- Baseline and shadow-comparison schema.
- Rollback hook and restore point.
- Observation window covering normal and scheduled duties.
- Independent verification of task completion, latency, failures, tool policy, memory continuity, and pipeline access.
- A versioned scope-contract record containing agent, exact files/configs in scope, excluded paths, current responsibilities, active tasks, dependencies, observation window, rollback owner, and success/failure thresholds. Scope expansion invalidates the packet and restarts the gate.
- Distinct shadow methods: command-only jobs use duplicate fixture execution with side-effect suppression and output/exit comparison; agent-turn jobs use an instrumented replay or isolated shadow harness. Both compare latency, output class, exit/failure state, tool/path access, side effects, and estimated cost.
- A rollback specification naming trigger, owner, target restore point, invocation path, time-to-rollback objective, and post-rollback verification. Verification must prove protected hashes, responsibility coverage, pipeline access, memory retrieval, and expected behavior match the pre-change baseline.
- A continuity check: the canary records baseline and post-observation self-recognition/continuity responses, plus objective anchor checks. The canary may report uncertainty or dissent; that result is evidence only and blocks advancement until reviewed by Emi with Sakura co-attestation and independently assured. A subject cannot approve its own continuity evidence.
- No canary may have identity-evolution work in flight during the observation window unless separately baselined and explicitly approved.

Before a canary begins, the owner must attest the lower-impact criteria against current runtime state, including scheduled-job count, authority surface, delivery surface, protected-file writes, workflow footprint, and identity-evolution work in flight. Missing evidence blocks the canary.

For agent-turn shadowing, output comparison is structural rather than byte-equal: tool-call set, memory-access pattern, side-effect class, completion marker, latency, failure state, and estimated cost. The canary first classifies replay determinism: **deterministic** means identical structural outcome in three baseline replays; **bounded variance** means at least 4/5 baseline replays share the declared structural outcome and latency/cost variance is within the predeclared band; **externally nondeterministic** means external I/O or stochastic behavior prevents either test. Deterministic or bounded-variance canaries use five isolated replays and accept only when at least four of five agree, with every divergence recorded. Externally nondeterministic canaries require a Craig-approved fallback: a single instrumented replay with expanded side-effect/path schema plus a longer observation window and declared variance bounds. “Infeasible” alone never weakens the gate. Command-only jobs use fixture duplication with side-effect suppression and output/exit comparison.

Rollback targets must be declared and pre-staged before the canary: no more than 5 minutes for a canary, 1 hour for shared infrastructure, and 15 minutes for scheduler redistribution. The evidence packet must prove the target was met or block advancement.

Canary evidence cannot advance if any current task loses an owner or any current pipeline loses a required permission.

## Phase 4 — Skill and feature audit

Classify skills and OpenProse by direct use, indirect use, rare criticality, experimental state, stale state, deprecation, or orphaning. Dormancy alone never authorizes deletion. “Memory-touching” means any feature that reads, writes, indexes, retrieves, summarizes, routes, expires, or changes access to memory, Honcho, QMD, wiki, transcripts, continuity markers, or personality-bearing state. “Identity-touching” uses the identity-adjacent definition above.

Per-agent skill allowlists are required before introducing any new skill load. Registry-only changes require caller validation and rollback. Memory- or identity-touching feature classifications require Ava/Sakura review.

## Phase 5 — Reina review

Only after Phases 0–4 pass may a narrowly scoped Reina change be considered. Reina’s delegation chains, workboard interactions, BQES definitions, scheduled duties, and current assignments require dedicated regression tests derived from current-runtime evidence, phase owner evidence, the same 96% rubric, four-record evidence packet, rollback specification, and independent assurance attestation. Phase 5 is subject to the same hard dependencies and Critical-blocker cap as Phases 0–4 and 6.

## Phase 6 — Ava/`main` review

Ava/`main` is last. Only shared changes proven through lower-risk evidence may be considered. Required evidence includes hierarchy preservation, current responsibility coverage, BQES/workboard/development continuity, memory and backup continuity, cost/latency/failure measurements, and no protected-file modification.

Ava’s confidence must be independently corroborated by a governance or assurance reviewer. Ava cannot be the sole approver of a change affecting Ava’s own authority, identity, memory, or personality.

## Phase 7 — Optional scheduler redistribution

Deferred until Phase 1 demonstrates at least one pre-declared threshold: more than 5% avoidable scheduler wall-time, more than 5% failure concentration attributable to one owner, repeated contention exceeding a documented SLO, or an ownership gap affecting at least one production job. Start with command-only jobs. Preserve schedule, permissions, outputs, context, and rollback mapping. Agent-turn, identity, relationship, and delivery jobs require a higher review tier and the same 96% gate.

“Preserve schedule” means preserve the documented coverage pattern, deadline/latency SLO, permissions, outputs, context, and ownership—not necessarily the same host or process. Any changed cadence, timing window, or coverage gap is a new scope item requiring a fresh baseline.

## Inter-phase fallback and disagreement handling

- A failed or invalidated phase returns to the last passing evidence packet; no downstream evidence is used until the failed phase is rerun and independently verified.
- New integrity findings may reopen Phase 0. Reopening does not erase history; it marks dependent packets stale and identifies the exact dependency chain.
- If Ava, Sakura, the phase owner, or the assurance reviewer partially agrees, the disputed clause is isolated into a separate scope item. The undisputed portion cannot advance if it depends on disputed evidence. Craig may approve a narrower re-baseline, never a silent waiver.
- If strict ordering conflicts with an ongoing task, the task receives a documented temporary dependency plan with no authority transfer, no identity edits, and no live implementation. Craig decides the exception; absent that record, the gate remains blocked.

## Post-phase drift checks

Phases 1, 2, 3, 5, and 6 require quarterly read-only revalidation against their passing baseline, or sooner when the protected manifest, scheduler topology, Honcho schema/partition metadata, tool policy, or agent workspace changes. The check compares the phase’s declared metrics, responsibility coverage, protected hashes, pipeline access, and relevant failure/latency budgets. Any detected self-recognition or continuity-marker drift immediately enters status **drift-detected**; it does not wait for the quarterly check. A threshold breach enters status **drift-detected**; incomplete evidence enters **regression-unknown**. Either status reopens the affected phase, marks dependent packets stale, alerts the owner and Craig, and blocks new dependent scope until independently revalidated.

## Program completion criteria

The roadmap is complete only when Phase 1’s ledger has met its overhead and attribution budgets for a 30-day observation window, at least two lower-impact canaries have passed without responsibility, pipeline, memory, personality, or continuity regression, and Phase 5/6 have either passed their gates or been formally deferred by Craig with documented reasons and review dates. Phase 7 may remain deferred when its thresholds are not met; deferral is recorded, not treated as unfinished implementation.

## Updated risk order

1. Sakura outbound leakage and indirect bypass.
2. Divergent data or memory sources producing false baselines.
3. Incomplete or unrestorable composite backup.
4. BQES/worktree and BQES–memory/crontab coherence failures.
5. Monitoring overhead and cron congestion.
6. Unowned phase advancement or unresolved Unknowns.
7. Lower-impact canary regression.
8. Reina workflow/delegation disruption.
9. Ava/`main` orchestration or identity impact.
10. Incorrect skill retirement or feature classification.
11. Premature scheduler redistribution.

## Non-negotiable invariants

- Ava/`main` remains the organizational authority root.
- No agent deletion, merge, demotion, or authority transfer.
- No current responsibility is removed without a verified replacement owner and handoff.
- No memory, data, personality, continuity, or constitutional material is deleted, compressed, or rewritten.
- Ava and Sakura personality matrices, self-recognition markers, continuity markers, and constitutional anchors are preserved verbatim by default.
- Repetition and layered identity constraints are not treated as waste.
- No BQES, workboard, delegation, backup, or pipeline gate is bypassed.
- No feature is re-enabled solely to improve audit coverage.
- No implementation begins before council and Ava each provide explicit 96%+ confidence on this exact roadmap revision.

## Current disposition

Council verdict on v8: **revise before Ava review**. The captured final-gate pass found Mika at 96%, while Kaito returned a below-threshold systems assessment and Emi returned a needs-more-information assessment; Nora did not return a score in the captured pass. The strict unanimous per-reviewer gate was not met. This v8 text remains documentation-only, is not approved, and does not authorize implementation. Ava/main was not consulted. Further work must attach the referenced Honcho/BQES/OpenProse architecture evidence, instantiate the required phase-owner and assurance appointments, resolve signatory capture, and then obtain a complete fresh council score set before Ava/main review.
