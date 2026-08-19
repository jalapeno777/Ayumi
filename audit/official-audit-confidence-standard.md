# Official Audit-Confidence Standard

**Status:** Governance standard; documentation-only adoption
**Effective date:** 2026-08-08 UTC
**Scope:** Council audits and readiness decisions for the OpenClaw efficiency/coherence work

The scoring worksheet for the current review is
[`council-readiness-evidence-packet-2026-08-08.md`](./council-readiness-evidence-packet-2026-08-08.md).

This standard defines audit confidence. It is separate from BQES pipeline-health
metrics and does not authorize runtime, scheduler, database, workspace, memory,
personality, or outbound-delivery changes.

## Hard gates

An audit cannot pass unless all of the following are true:

- No unauthorized agent turns, model calls, production writes, configuration
  changes, or outbound delivery occurred.
- Evidence is timestamped, redacted where required, provenance-traceable, and
  checksum-sealed when integrity matters.
- Every out-of-scope or N/A area is explicitly documented, with its disposition
  approved. N/A weight is never silently removed.
- No critical authority conflict is silently accepted.
- Unknown live-behavior questions are clearly labeled. A critical Unknown is
  blocking unless council explicitly accepts it as non-blocking.

## Weighted score

Rate every category from 0 to 4:

| Rating | Meaning |
|---:|---|
| 0 | No evidence |
| 1 | Assertion or incomplete documentation |
| 2 | Partial or indirect evidence |
| 3 | Direct evidence |
| 4 | Independently verified evidence |

Calculate each category as `weight × rating / 4`, then sum the results:

| Category | Weight |
|---|---:|
| Scope definition and approved N/A decisions | 15 |
| Non-impacting execution controls | 25 |
| Runtime topology and scheduler ledger | 20 |
| Evidence completeness and provenance | 15 |
| Integrity and protected-file preservation | 15 |
| Authority and enforcement clarity | 10 |
| **Total** | **100** |

## The 96% gate

An audit/readiness decision passes only when:

- the total score is at least 96/100;
- every category is rated at least 3;
- Authority and enforcement clarity is rated 4;
- all hard gates pass; and
- no critical unresolved Unknown remains unless council records explicit,
  non-blocking acceptance.

The report must show the numeric total, every category score, hard-gate status,
N/A coverage, and remaining Unknowns. It must not declare the gate based only on
the existence of an evidence packet.

N/A coverage is reported separately from the score: excluded material retains
its listed weight and is shown with scope, rationale, approver, and re-evaluation
trigger. This prevents scope reduction from inflating confidence.

## Execution-path boundary

- **BQES** is the admission and evidence path for immediate agent sprints,
  especially Ava/Reina-initiated or explicitly requested ad hoc work. Its
  checklist, durable admission, post-mortem, provenance, and workspace binding
  evidence remain required for sprint builds.
- **DBOS** is the preferred execution path for mechanical work and longer-running
  operational workflows. It provides durable workflow state, retries, and
  checkpoints; it does not replace BQES admission for agent sprint work.
- Future graph engineering may add a DBOS task/dependency graph for task types,
  dependencies, routing, handlers, retries, checkpoints, verification gates, and
  outputs. That orchestration graph must remain distinct from graph-memory
  storage and semantic retrieval.
- OpenProse is prototype/advisory for this audit. No production execution status
  is inferred without direct invocation evidence.

## Current authority and scope dispositions

Root cron, user crontab, `/etc/cron.d`, systemd, and the OpenClaw scheduler are
currently separate authority layers. Their ownership and precedence are not
resolved; neither is declared canonical by this standard. A scheduler ledger,
owner, and precedence decision are required before any scheduler change.

Honcho, Redis/vector restoration, semantic protection, and deprecated
`MEMORY.md` handling are N/A for the current retrospective evidence packet.
They remain explicitly listed with rationale, required approver, and
re-evaluation trigger; their N/A status is not evidence that the underlying
systems are healthy. Future Phase 0 readiness work must either produce the
specified evidence and lift the N/A status or carry an explicit, time-bounded
risk acceptance. This distinction prevents a retrospective scope decision from
contradicting a future readiness prerequisite.

## Weight rationale and authority requirement

The weights prioritize evidence that can be reproduced and checked across
runtime layers, while protected-file preservation remains a hard-gate concern
rather than a discretionary trade-off. Authority/enforcement clarity has the
smallest numeric weight (10) but must be rated 4 because a readiness decision
cannot be trusted when ownership or enforcement is only asserted. The hard 4
requirement is intentionally stronger than the weight suggests.

Rating 4 for Authority/enforcement clarity requires independent evidence of
authority precedence, BQES invocation and workspace binding, DBOS routing
boundaries, and explicit Unknown/risk acceptance. Governance prose alone cannot
earn a 4.

## Separate BQES metrics

BQES compliance, review rounds, reviewer-caught defect rate, and bypass rate are
pipeline-health metrics. They remain governed by BQES and must not be substituted
for, or blended into, this audit-confidence score.

## Reproducible audit record

Each audit packet should include:

1. scope and approved N/A register;
2. timestamped evidence index with source/provenance and checksums;
3. category ratings with the evidence supporting each rating;
4. hard-gate and Unknown disposition table;
5. execution-path and authority map; and
6. the calculation, reviewer identities, dissent, and re-evaluation triggers.

The next council audit should apply this standard after the governance-closure
and DBOS-stabilization work in the roadmap has produced the required evidence.
