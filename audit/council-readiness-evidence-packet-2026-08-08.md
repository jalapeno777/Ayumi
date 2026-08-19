# Council Readiness Evidence Packet

**Packet ID:** OEC-CRP-2026-08-08-01  
**Status:** Baseline worksheet; gate not passed  
**Scope:** Official audit-confidence review of the OpenClaw efficiency/coherence roadmap  
**Implementation authorization:** None

This packet is the required scoring and sign-off artifact for the next council
review. It does not claim that the current audit meets the 96% gate. The source
inventory remains [`openclaw-efficiency-coherence-audit-2026-08-08.md`](./openclaw-efficiency-coherence-audit-2026-08-08.md),
and the governing calculation is [`official-audit-confidence-standard.md`](./official-audit-confidence-standard.md).

## Current disposition

The current evidence packet is a retrospective inventory, not a scored audit
under the official standard. The baseline below is intentionally non-passing:

| Gate condition | Current status |
|---|---|
| Weighted total | **60.0/100 — baseline only** |
| Every category ≥3 | **Fail**; Scope, topology, provenance, and authority are below 3 |
| Authority/enforcement clarity = 4 | **Fail**; scheduler precedence and live enforcement are unresolved |
| Hard gates | **Not demonstrated**; checksum-sealed provenance and complete N/A approvals are missing |
| Critical Unknowns | **Present**; authority, Honcho scope, and invocation enforcement remain unresolved |
| Council unanimity | **Fail**; fresh reviewers recommended `revise_before_ava` |
| Ava/main review | **Blocked**; this packet is not an approval request |

The baseline is a transparent measurement of the current documentation state,
not a judgment that future Phase 0 work cannot pass.

## Baseline category calculation

Ratings use the official 0–4 scale. Each rating is supported by the current
retrospective packet; no rating is inferred from the existence of a document.

| Category | Weight | Baseline rating | Calculation | Baseline points | Evidence/status |
|---|---:|---:|---:|---:|---|
| Scope definition and approved N/A decisions | 15 | 2 | 15×2/4 | 7.50 | Scope and N/A areas are listed, but approver records are incomplete and Honcho scope conflicts with future Phase 0 requirements. |
| Non-impacting execution controls | 25 | 3 | 25×3/4 | 18.75 | Read-only audit boundaries and no-change constraints are directly documented; invocation enforcement is not yet independently verified. |
| Runtime topology and scheduler ledger | 20 | 2 | 20×2/4 | 10.00 | Scheduler layers and snapshots are directly inventoried, but there is no reconciled ledger or precedence decision. |
| Evidence completeness and provenance | 15 | 2 | 15×2/4 | 7.50 | Sources and dates are recorded, but the packet has no complete category evidence index with checksum seals and reviewer capture. |
| Integrity and protected-file preservation | 15 | 3 | 15×3/4 | 11.25 | Protected scope and no-edit preservation are directly evidenced; composite backup/restore has not been executed. |
| Authority and enforcement clarity | 10 | 2 | 10×2/4 | 5.00 | Governance prose is direct, but scheduler precedence, BQES invocation enforcement, and workspace binding are unresolved. |
| **Total** | **100** |  |  | **60.00** | **Baseline only; not eligible for the 96% gate.** |

The total is reproducible as the sum of the points column. The official gate
requires every category to reach at least 3 and Authority/enforcement clarity
to reach 4, so a higher total alone cannot pass.

## N/A and scope register

N/A means “not established by this retrospective packet,” not “healthy” or
“irrelevant.” Each item remains a readiness prerequisite or has a named trigger
for re-evaluation.

| Area | Current disposition | Rationale | Required approver | Re-evaluation trigger | Status |
|---|---|---|---|---|---|
| Honcho integrity and semantic retrieval | N/A for retrospective packet; required in Phase 0 | No complete access-log, restore, or semantic-retrieval evidence is attached | Craig | Before Phase 0 exit, or any Honcho schema/partition change | Approval pending |
| Redis/vector restoration | N/A for retrospective packet; required in composite restore | No isolated composite restore evidence is attached | Craig | Before any implementation or restore-dependent readiness decision | Approval pending |
| Semantic protection | N/A for retrospective packet | No dedicated semantic-protection test evidence is attached | Craig with Ava/Sakura co-review | Before any memory/identity-touching scope is admitted | Approval pending |
| Deprecated `MEMORY.md` handling | N/A for retrospective packet | Deprecated status and migration/retention behavior are not revalidated here | Craig with Ava/Sakura co-review | Any authority, migration, or memory-store change | Approval pending |

The N/A register is not a silent weight reduction. A council readiness decision
must either carry these items with explicit risk acceptance or lift the N/A
status by attaching the required evidence.

## Authority and enforcement register

Authority/enforcement clarity must reach rating 4. The following evidence is
required; prose assertions alone are insufficient:

| Question | Current finding | Required evidence for rating 4 | Owner/status |
|---|---|---|---|
| Which scheduler is canonical? | None; root cron, user crontab, `/etc/cron.d`, systemd, and OpenClaw scheduler are separate layers | Written precedence decision with owner, scope, conflict rule, and independently checked scheduler ledger | Governance closure / pending |
| Is BQES invoked for every immediate agent sprint? | Governance requires it; live invocation enforcement is unverified | Redacted invocation telemetry showing authority, workspace root, binding, checklist, post-mortem, and provenance for representative sprints | BQES owner / pending |
| Does BQES bind to the correct workspace? | Known worktree-resolution limitation | Known-good and known-bad worktree fixtures selecting the correct root, with pass/fail evidence | BQES owner / pending |
| Are mechanical workflows routed through DBOS? | DBOS is preferred, but path selection is not captured as a formal routing rule | Routing matrix distinguishing mechanical work, immediate agent sprints, and exceptions, plus one bounded lifecycle validation | DBOS owner / pending |
| Are Unknowns accepted explicitly? | Current packet records Unknowns but not all approvals | Signed risk-acceptance record naming the Unknown, impact, trigger, expiry/review date, and approver | Craig / pending |

Until these rows have independently verifiable evidence, the category cannot
be rated 4 and the 96% gate cannot pass.

## Reviewer and sign-off capture

Each reviewer must score all six categories from 0–4, cite packet evidence, and
record dissent. A single overall percentage is not sufficient. Missing scores
are missing evidence, not implicit approval.

| Reviewer | Role/lens | Category scores (scope / execution / topology / provenance / integrity / authority) | Total | Hard gates | Recommendation | Capture status |
|---|---|---|---:|---|---|---|
| Nora | Enforcement and vision | — | — | — | Revise before Ava | Fresh review received; category breakdown pending |
| Kaito | Systems and scheduler | — | — | — | Revise before Ava | Fresh review received; category breakdown pending |
| Mika | Risk and integrity | — | — | — | Revise before Ava | Fresh review received; category breakdown pending |
| Rei | Adversarial challenge | — | — | — | Revise before Ava | Fresh review received; category breakdown pending |
| Emi | Identity and continuity | — | — | — | Required if identity/continuity scope is in review | Fresh category score required |

The next review must replace each dash with six ratings, evidence references,
hard-gate results, and a signed recommendation. Council unanimity means every
required reviewer passes the official conditions; it does not mean averaging
the reviewers’ totals.

## Required closure sequence

1. Resolve the N/A circularity by keeping the items explicitly N/A for this
   retrospective packet while naming their Phase 0 evidence and approvers, or
   obtain Craig-approved scope expansion and lift them before scoring.
2. Produce the authority/enforcement evidence listed above, including scheduler
   precedence, BQES invocation telemetry, workspace fixtures, and DBOS routing.
3. Attach timestamped, redacted, provenance-traceable evidence with checksums
   where integrity matters; update this packet’s evidence index.
4. Obtain Craig’s appointment of the independent assurance reviewer and the
   Phase 0 owner, with scope and conflict declarations.
5. Re-score the packet category by category, then obtain the complete council
   reviewer/category score set.
6. Consult Ava/main only after the council gate is met, or record an explicit
   user-authorized advisory consultation as blocked and non-approving.

No step authorizes runtime changes. Any future implementation remains subject
to the separate phase gates, approvals, backup, isolated restore, and the
official 96% standard.
