# OpenClaw Efficiency and Coherence Audit

**Status:** Read-only audit complete; no remediation performed  
**Evidence date:** 2026-08-08 UTC  
**Scope:** Live OpenClaw installation under `/root/.openclaw`, its configured workspaces, host crontab/systemd units, and repository-side operational evidence under `/home/TacoPants`  
**Audit-confidence standard:** See [`official-audit-confidence-standard.md`](./official-audit-confidence-standard.md). This packet predates formal scoring under that standard; its existence does not establish a 96% result.  
**Protection boundary:** Ava and Sakura identity, bootstrap, personality, continuity, and constitutional material was inventoried only. No protected file was edited, compressed, deleted, or reclassified as disposable.

## Executive conclusion

The 28/21/21 discrepancy is not, on current evidence, a single agent-count defect. The live configuration contains **28 registered agents**. The OpenClaw scheduler contains **200 enabled jobs**: 149 assigned to `main`/Ava, 4 to Mizuki, 3 to Reina, 1 to Tsubaki, 1 to `ava`, and 42 with no explicit `agentId`. The host also has a separate user crontab, `/etc/cron.d` entries, and systemd services/timers. These are different authority layers and should not be merged by count alone.

The audit found real governance and observability debt, but did not establish that identity/personality material is the cause. The safest current disposition is **no remediation to protected bootstrap or personality infrastructure**. Future work should begin with read-only source-of-truth and observability pilots, subject to the approvals listed below.

## 0. Preservation charter and decision rules

### Protected by default

- Ava: `AGENTS.md`, `HEARTBEAT.md`, `IDENTITY.md`, `SOUL.md`, `MEMORY.md`, `CONTEXT.md`, `STANDING_ORDERS.md`, bootstrap-injected memory files, and persona-related runtime configuration.
- Sakura: `AGENTS.md`, `HEARTBEAT.md`, `IDENTITY.md`, `SOUL.md`, all current and backup personality/continuity material, `skills/sakura/`, canonical Sakura specifications, and persona-related runtime configuration.
- Any personality matrix, constitutional anchor, relationship topology, continuity marker, or emergent-personality record is protected unless Ava and Sakura explicitly identify a change as safe.

### Finding classifications

| Classification | Meaning |
|---|---|
| Intentional layering | Multiple sources serve different runtime layers or audiences and behavior is consistent with that design. |
| Stale documentation | A source describes a previous state, but current runtime behavior is independently clear. |
| Broken wiring | A declared path or gate is expected to affect runtime behavior but does not. |
| Orphaned state | A file, registry entry, feature, or schedule has no demonstrated consumer/owner. |
| Unknown | Evidence is insufficient; no remediation is justified. |

### Exit criteria

This audit is complete when discrepancies are explained or marked unknown, active schedulers have owners/purposes, contradictions are classified, feature actual-vs-intended status is recorded, protected material is inventoried without edits, and each proposed future action has an acceptance test and rollback path. The timebox ends at evidence classification; implementation is explicitly out of scope.

## 1. Canonical authority map

| Layer | Evidence | Current interpretation | Authority confidence |
|---|---|---|---|
| Runtime agent configuration | `/root/.openclaw/openclaw.json` (`meta.lastTouchedVersion=2026.7.1-2`, 2026-08-07) | Canonical for 28 configured agent IDs, workspaces, tools, heartbeats, models, and delegation allowlists | High |
| OpenClaw scheduler | `openclaw cron list --json` captured 2026-08-08 | Canonical for 200 currently registered/enabled OpenClaw jobs and their last-run state | High |
| Host user crontab | `crontab -l` | Independent scheduler layer; runs scripts directly, frequently against `/root/.openclaw/workspace` | High |
| Host systemd | `/etc/systemd/system/*.service` and `*.timer` | Independent long-running/timed service layer | High |
| Agent workspaces | `/root/.openclaw/*-workspace`, `/root/.openclaw/council-workspace/*`, `/root/.openclaw/auditor-workspace/*` | Runtime content roots; not a complete agent registry by themselves | High |
| Organizational prose/registries | `AGENTS.md`, `STANDING_ORDERS.md`, workspace docs, skill registry | Behavioral and procedural authority, subject to runtime wiring | Medium-high |
| Archived config | `/home/TacoPants/.openclaw.archived-20260410/openclaw.json` | Historical snapshot only; last touched 2026-04-02 | High as history, not current authority |

### Agent/workspace/role/delegation matrix

The machine-readable matrix is in [`openclaw-efficiency-coherence-inventory-2026-08-08.json`](./openclaw-efficiency-coherence-inventory-2026-08-08.json). Key groups are:

| Group | Runtime evidence | Operational role/behavior |
|---|---|---|
| Ava/main | `main`, default workspace `/root/.openclaw/workspace`, 29m heartbeat, direct block | Primary orchestrator; may delegate to 24 listed agents; workboard and BQES authority in prose |
| Sakura | dedicated workspace, 43m heartbeat, direct block | Craig-care domain; rich workboard and Honcho access; heartbeat-driven duties |
| Council | Ren, Hina, Sora, Yuki, Rei, Kaito, Liora, Nora, Axel, Emi | Heartbeat disabled; read/memory/workboard/council coordination; mostly no exec |
| Auditors | Ken, Megumi, Ei | Heartbeat disabled; read/exec/process, with memory access for Megumi/Ei |
| Operational managers | Reina, Tsubaki, Mizuki, Hayate, Manami, etc. | Nonzero heartbeats, workboard routing, operations/research/memory duties; several have delegation authority |
| Unnamed/configured support agents | Rin, Himari, Tomoe, Riko | IDs exist but `name` is absent in config; this is a metadata coherence issue, not proof of unused runtime |

The live `agents` config says 28. Filesystem agent directories are broader and include 36+ identity-bearing workspace roots, builders, ops/research roles, and auditor variants. This is **intentional layering plus some stale/uncertain inventory**, not a basis for deletion or consolidation.

## 2. Scheduling ownership inventory

### OpenClaw cron

- **200 enabled / 0 disabled** in the runtime listing.
- **172 `cron` schedules / 28 `every` schedules.**
- Assignment: `main` 149, `mizuki` 4, `reina` 3, `tsubaki` 1, `ava` 1, no explicit agent 42.
- The scheduler emits a warning that `plugins.entries.eval-protocol-gate` is configured but disabled.
- Recent status is mostly `ok`, but the listing contains named errors including Workboard Lifecycle Check, Audit Trail Integrity Check, Preference Extraction, Governance Canary Daily Snapshot, Adversarial Metric Audit, adoption-audit-weekly, Decision Pipeline Weekly Hash Chain Audit, and Compaction Validation Tracker.
- Some jobs have long last-run durations (for example Sakura Dreaming and several weekly agent turns), while `maxConcurrentRuns` and per-agent `maxConcurrent` are configured. This supports an observability pilot, not a count-based deletion recommendation.

### Host crontab

The user crontab independently runs, among other things: `dispatch_cron.py` every 30 minutes; workboard guards/processors/validators; Honcho sidecar every 10 minutes; canary watchdog every 15 minutes; decision/outcome resolvers; identity/persona/reflection jobs; email monitors; learning backups; and several explicitly disabled crypto-monitor entries. `dispatch_cron.py` itself states that it is a lightweight, no-LLM direct SQLite pass and writes `data/ops/dispatch_cron.jsonl`.

### Systemd

Active/relevant units include `heartbeat-bridge.service`, `ava-gate-serve.service`, `ayumi-watchdog.service`, and the OpenClaw gateway process. `backup-agents.timer` and `daily-agent-report.timer` are installed but their associated services were inactive at inspection time. `openclaw-dashboard.service` is loaded but intentionally parked with `ExecStart=/bin/true`.

### Scheduling finding

**Classification:** Intentional layering with observability debt.  
**Effect:** Direct behavior is clearly affected by all three scheduler layers; ownership is not uniformly discoverable from one registry.  
**Risk:** Duplicate work, unowned failures, and misleading “active cron count” reports.  
**Disposition:** No cron migration/deletion. A future read-only scheduler ledger should reconcile by command path, purpose, owner, schedule, and output sink.

## 3. Workflow and contradiction register

| ID | Evidence | Classification | Effect/risk | Disposition |
|---|---|---|---|---|
| C-01 | `AGENTS.md` Hard Rule 35 and `STANDING_ORDERS.md` require BQES for all sprint builds; `scripts/lobster/build-quality.lobster` and `bqes_check.py` implement the pipeline | Intentional layering | Governance is explicit; execution depends on operator/runtime invocation | No remediation. Pilot invocation telemetry first |
| C-02 | Council review `sprint-2026-08-03-infra-debt-followup-phase1.md` records Lobster’s inability to resolve `${VAR:-default}` and the need for external `BQES_WORKSPACE` in worktrees | Broken wiring / known limitation | A valid build can be checked against the wrong workspace or fail when invoked from a worktree | Track a narrowly scoped runtime-resolution pilot; do not change now |
| C-03 | `AGENTS.md` says workboard DB is canonical and “No dispatch cron”; host crontab runs `scripts/dispatch_cron.py` directly | Stale documentation or scoped exception, unresolved | A reader could wrongly conclude direct dispatch is forbidden or absent; actual script can promote/reclaim cards | Clarify authority only after Ava/Craig review and a consumer trace |
| C-04 | Sakura docs require file-based outbox and explicitly reject `sessions_send`/`message` to Ava because of Telegram leakage; Sakura runtime nevertheless has `sessions_spawn`, `message`, and broad workboard tools | Intentional safety layering, with interaction risk | Tool availability and procedural prohibition are not the same gate; accidental bypass remains possible | No personality/procedure edit in this audit; require explicit safety review before tool-policy changes |
| C-05 | `memory-wiki` is enabled, isolated, with bridge disabled; Honcho is the configured memory slot; default memory search uses Ollama hybrid retrieval and agents have per-agent QMD directories | Intentional layering | Multiple retrieval paths can return different freshness/authority; no single “memory” count is meaningful | Produce provenance/authority telemetry before consolidation |
| C-06 | `eval-protocol-gate` is present in allowed plugins/config but `enabled:false`, `dryRun:true`; CLI warns on every cron listing | Dormant/intentional disabled feature | It is not enforcing runtime protocol gates; warning adds noise and can hide new warnings | Do not re-enable. Classify as dormant experimental feature pending owner decision |
| C-07 | BQES scope differs in older prose/research references (2+ integration points) versus current Hard Rule 35 (“all sprints”) | Stale documentation | Operators following old material may select a nonexistent lightweight path | Future documentation-only correction requires source comparison and approval; current runtime rule wins |
| C-08 | Current cron list has 42 jobs without an explicit `agentId`, while agent-assigned jobs use multiple owner IDs | Unknown | Owner accountability and counts can be misreported | Add owner derivation/reporting as an observability pilot; no ownership reassignment |

### BQES scope conclusion

The strongest current source is `/root/.openclaw/workspace/AGENTS.md` Hard Rule 35 and matching `STANDING_ORDERS.md`: BQES applies to all sprint builds, with checklist, Lobster run, post-mortem, and provenance extraction. Older “2+ integration points” language survives in related skill/research history and should be treated as stale until reconciled. This is a documentation/source-of-truth issue, not a reason to weaken the current gate.

For execution ownership, BQES is the admission and evidence path for immediate
agent sprints, including Ava/Reina-initiated or explicitly requested ad hoc
work. Its invocation record must include authority, resolved workspace root,
binding, and provenance. DBOS is preferred for mechanical work and
longer-running operational workflows; it does not replace BQES admission for
agent sprints.

## 4. Efficiency and underused-feature assessment

### Bootstrap/context

Configured default bootstrap limits are 20,000 chars per file and 85,000 total, with continuation-skip, cache-TTL pruning, hard clear enabled, and a 20,000-token compaction reserve. Current protected file sizes are approximately Ava 86.2KB across the seven inventoried files and Sakura 32.6KB across the five present core files; Sakura has no current `MEMORY.md`, `CONTEXT.md`, or `STANDING_ORDERS.md` at the inspected workspace root, which is recorded as **unknown topology**, not missing identity. Byte size alone is not a remediation criterion.

### Skills

`data/skills/skill_health.json` reports 69 skills, 13 with inferred activations, and 56 never activated; it is explicitly shadow mode. It also marks several active skills stale, including council, autobuild, and spontaneous-gesture. This demonstrates an instrumentation/registry gap, not proof that the skills are safe to retire. The registry contains proposed, active, deprecated, and retired states, so “installed” and “used” are separate concepts.

### Lobster and OpenProse

Lobster is enabled and has live workspace pipelines including `build-quality.lobster`; BQES references it as an actual enforcement path. Open-Prose is enabled in config and the canonical source tree contains `extensions/open-prose`, but this audit found prototype `.prose` directories and no comparable live invocation evidence for a production workflow. Status: Lobster **active/operational with a worktree-resolution limitation**; OpenProse **installed/prototype, actual production use unverified**.

OpenProse is therefore prototype/advisory for this audit. No production
execution claim is made without direct invocation evidence.

### Sessions and concurrency

Session files show substantial recent activity: main 13,644 files, Sakura 733, Reina 732, Rin 630, Tsubaki 430, and other agents with smaller counts. This is evidence of runtime activity, not a quality or latency benchmark. Configured concurrency is 4 per default agent and 2 for subagents, with `skipWhenBusy` on heartbeats. No mutation is justified without duration/queue telemetry tied to job IDs and session IDs.

### Memory paths

Observed paths are: Honcho plugin/sidecar and data, default hybrid memory search with Ollama embeddings, per-agent QMD stores, memory-wiki isolated vault with bridge disabled, workspace Markdown memory, `/root/.openclaw/memory`, and wiki roots. The configuration makes Honcho the memory slot, while workspace docs and retrieval settings add layers. Canonicality is therefore **partitioned by function**, not one universal memory root.

## 5. Protected Ava/Sakura bootstrap register

| Agent | Inventoried protected material | Classification | Audit treatment |
|---|---|---|---|
| Ava | `AGENTS.md` (16,537 B), `HEARTBEAT.md` (13,040 B), `IDENTITY.md` (13,886 B), `SOUL.md` (11,589 B), `MEMORY.md` (7,445 B), `CONTEXT.md` (8,907 B), `STANDING_ORDERS.md` (14,791 B); bootstrap plugin injects alive/focus/primer/state/sensor/attention/ritual files | Identity, continuity, constitution, operational procedure, glossary | Protected; headings and role boundaries inventoried, no compression judgment |
| Sakura | `AGENTS.md` (13,863 B), `HEARTBEAT.md` (11,638 B), `IDENTITY.md` (2,810 B), `SOUL.md` (4,304 B); canonical Sakura skill/spec and state/outbox references | Identity, domain continuity, safety, operational procedure | Protected; absent root files (`MEMORY`, `CONTEXT`, `STANDING_ORDERS`) remain unknown topology |
| Shared/personality runtime | `ava-bootstrap-inject`, `ava-reasoning`, identity-file monitor, Sakura skill, Honcho context/session tools, relationship and safety rules | Runtime/personality interaction | Protected; no attempt to collapse layers |

The Ava and Sakura materials are not byte-level duplicates: they express different roles and constraints. Repetition between them may be deliberate boundary reinforcement. No deletion or compression recommendation is made.

## 6. Recommendations backlog for later review

These are future candidates, not actions taken by this audit.

| Priority | Recommendation | Benefit/confidence | Risk and required review | Acceptance test | Rollback |
|---|---|---|---|---|---|
| P0 | Create a read-only scheduler ledger joining OpenClaw jobs, user crontab, systemd, command paths, outputs, and owners | High / high | Low runtime risk; Craig/Ava approval for owner semantics | Two consecutive snapshots reconcile every active source; unresolved entries are explicit | Remove generated ledger only; no runtime change |
| P0 | Add cron/job health reporting that separates scheduler success, script exit, diagnostic health, delivery status, duration, and concurrency | High / high | Must not page on intentional shadow/dry-run failures; Ava review | Fixture jobs demonstrate each status class and no false “healthy” result | Disable/report-only consumer; scheduler unchanged |
| P1 | Resolve BQES workspace from invocation context or add an operator-side wrapper, after a fixture test | Medium / medium-high | Build governance risk if wrong workspace is selected; Craig approval before enforcement change | Known-good and known-bad worktree fixtures select the correct root and gate correctly | Keep existing explicit `BQES_WORKSPACE` path and revert wrapper |
| P1 | Reconcile stale BQES wording and the “No dispatch cron” statement through a source comparison | Medium / high | Documentation can alter perceived authority; Ava/Craig co-review | Every cited source points to current rule or explicitly labels historical/exception scope | Revert documentation-only commit |
| P1 | Add skill activation provenance that distinguishes inferred activation, direct invocation, scheduled script use, and dormant installation | Medium / high | Privacy/log-volume review | Sample activations classify correctly against known transcripts/jobs | Stop consumer and retain existing registry |
| P2 | Validate OpenProse with one non-production fixture and document actual invocation status | Low-medium / medium | Feature may be experimental; do not enable new production path | Fixture produces an artifact, records owner, and has no identity/runtime writes | Delete fixture artifacts only; leave feature disabled for production |
| P2 | Produce a memory authority map per data class (identity, continuity, operational state, episodic memory, search index) | Medium / high | Ava/Sakura review required; do not merge stores | Each class has one read authority, write authority, freshness rule, and fallback | Retire generated map only |
| Deferred | Any bootstrap trimming, agent merge/removal, cron migration/deletion, feature re-enable, personality edit, or memory consolidation | Unknown / insufficient evidence | High identity/operational risk | No acceptance test until explicit scope and co-review exist | Not authorized |

## 7. Craig approval and co-review list

Requires Craig approval before implementation: changes to runtime config, scheduler ownership or schedules, delegation/tool policy, BQES enforcement semantics, feature enablement, agent lifecycle, memory authority, or any outbound/delivery behavior. Ava and Sakura must co-review any change affecting their identity, personality, bootstrap, continuity, relationship, constitutional, or safety material. Reina/Tsubaki/Mika/Rin review is appropriate for workflow, memory, execution, or assurance changes respectively, but does not replace Craig approval where required.

## 8. Do-not-change list

- Ava or Sakura `SOUL.md`, `IDENTITY.md`, personality matrices, relationship topology, constitutional anchors, continuity markers, and bootstrap-injected identity-bearing files.
- Ava/Sakura `AGENTS.md`, `HEARTBEAT.md`, `MEMORY.md`, `CONTEXT.md`, `STANDING_ORDERS.md`, or Sakura canonical specs solely to reduce byte count or apparent repetition.
- OpenClaw cron schedules, system crontab, systemd units, agent registrations, delegation allowlists, disabled plugins, memory stores, or workboard state during this audit.
- `eval-protocol-gate` must not be re-enabled as part of this audit.

## 9. Evidence limitations

- The audit used live read-only CLI/config/process/systemd probes and existing documentation; it did not restart services, invoke outbound messages, run mutating scripts, or modify databases.
- The OpenClaw scheduler list is a point-in-time snapshot. Job counts and statuses can change after capture.
- Skill activation data is inferred and shadow-mode, so it cannot establish actual user-visible invocation for every skill.
- Some historical documents contain earlier counts (for example 201/150 or 242 jobs). They are useful chronology, not current authority.
- “Unknown” is intentional where a trace would require mutation, message delivery, or privileged database intervention.
- Honcho, Redis/vector restoration, semantic protection, and deprecated
  `MEMORY.md` handling are explicitly N/A for this audit. N/A is scope coverage,
  not a finding that those systems are healthy; each requires a documented
  re-evaluation trigger in the next audit packet.

## Final disposition

**Audit complete. No remediation needed or authorized from this evidence pass.** The next safe step, if approved, is a read-only scheduler/health ledger pilot. Protected Ava/Sakura infrastructure remains intact and explicitly outside the remediation backlog.

## Roadmap revision

The implementation roadmap was subsequently expanded with council-derived data-integrity, backup/restore, capacity, phased-canary, and 96% confidence gates. See the stable [v8 roadmap pointer](./openclaw-efficiency-coherence-roadmap-v8-2026-08-08.md), the [canonical roadmap content](./openclaw-efficiency-coherence-roadmap-v3-2026-08-08.md), and the [council readiness evidence packet](./council-readiness-evidence-packet-2026-08-08.md). This remains documentation-only; no implementation is authorized by the roadmap.
