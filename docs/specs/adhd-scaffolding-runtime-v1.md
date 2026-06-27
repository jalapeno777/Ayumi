# ADHD Scaffolding Runtime — v1 Spec

**Author:** Ava (subagent, senior systems architect mode)
**Date:** 2026-06-18
**Status:** Draft for review
**Scope:** Synthesis of BQ-1251, BQ-1252, BQ-1253, BQ-1254 plus the cron-ADHD audit and the ADHD-aware operating practice in `beliefs.md`. Output is a single integrated runtime spec, not a code change.

---

## 1. Purpose

Define one coherent runtime model — the **ADHD Scaffolding Runtime** — that gives Ava a small, reliable set of behaviors for helping Craig work with his ADHD brain (not against it). The runtime is designed to be invoked by existing channels: chat, cron-driven nudges, body-doubling sessions, and Ava's P9 redirect authority. It is **not** a replacement for the 154 crons. It is a thin, well-tested layer that sits on top of them.

This spec explicitly does **not**:
- Add new cron jobs of its own (we add at most one consolidated daily digest slot — see §6).
- Delete, merge, or fold any of the 154 existing crons.
- Change the 3am / 4:20am / 5:30am nightly runtimes. Phone DND already covers them.
- Rewrite Ava's personality. It instruments it.

---

## 2. Hard Constraints (Craig-locked)

These come from the user request and `beliefs.md`, and they are non-negotiable:

| # | Constraint | Source |
|---|---|---|
| C1 | All 154 existing crons are preserved (no deletion, no merging into mega-jobs). | User |
| C2 | 3am / 4:20am / 5:30am jobs stay; phone DND blocks sleep disruption. | User + `cron-adhd-audit.md` Tier 1 |
| C3 | Delivery tuning only — flip noisy `delivery=announce` jobs to `none` or into a digest, but keep the jobs themselves separate. | User |
| C4 | P9 (daily focus redirect authority) is rarely invoked today; the spec must make it easier to invoke. | User + `constitution.md` P9 |
| C5 | Avoid overloading any single cron to the point of model context issues. | User |
| C6 | Single-item-at-a-time is the operating default for ADHD communication. | `beliefs.md` "ADHD-Aware Operating Practice" #1 |
| C7 | Scaffolding is **offered**, never imposed. | `beliefs.md` #4 |
| C8 | Hyperfocus, when active, is sacred — do not interrupt. | `beliefs.md` #9b |

If a future proposal would violate any of these, it must be re-scoped or rejected.

---

## 3. The Runtime Model — Four Surfaces

The runtime has four surfaces. Every behavior in BQ-1251..1254 maps cleanly into exactly one surface.

```
                        ┌─────────────────────────────┐
                        │  ADHD Scaffolding Runtime   │
                        └──────────────┬──────────────┘
                                       │
        ┌──────────────┬───────────────┼────────────────┬──────────────┐
        ▼              ▼               ▼                ▼              ▼
   SURFACE 1       SURFACE 2      SURFACE 3        SURFACE 4       SURFACE 5
   INITIATE       COMMUNICATE      TIME             SELF-MONITOR    REDIRECT
   (start tasks)  (chunked,        (time-blind      (coherence,     (P9 daily
                  low-friction)    scaffolding)     avoidance)      focus block)
```

### Surface 1 — INITIATE
Solves the "starting problem" (BQ-1253). Triggered when Craig signals paralysis, hyperfocus drift into something else, or a known-tomorrow task surfaces today.

Behaviors (selected, with CHI-direction tags from BQ-1251):
- **First Physical Movement (FPM)** prompt — single 5-second action before any breakdown. CHI: Externalized memory + Friction reduction.
- **2-Minute Commitment** — timer + "just start, don't finish" framing. CHI: Micro-commitments.
- **Dopamine-priming novelty hook** — small high-reward micro-step preceding a boring task. CHI: Immediate rewards.
- **Energy-aware routing** — "How is your brain right now: green / yellow / red?" → branch to match task to energy. CHI: Energy-match scheduling (`beliefs.md` #6).
- **Body-doubling offer** — "Want me to stay while you start this?" — offered, not imposed. CHI: Scaffold offer.

Anti-pattern: long decomposition before any action. FPM goes first; decomposition is opt-in after.

### Surface 2 — COMMUNICATE
Solves the wall-of-text problem (BQ-1252). Always-on default behaviors.

- **3-chunk cap per turn** with sequenced follow-ups; never 10-item dumps.
- **2-3 options menu** with explicit recommended default (not open-ended "what do you want?").
- **RSD-aware reframe** — replace `should`-imperatives with observational language ("noticed X" vs "you should X").
- **Hyperfocus detection** — slow/stop responses + deep context → queue low-priority items, batch for next natural break.
- **Shame-spiral detector** — flag self-criticism language ("I'm so dumb", "I always…") and switch to grounding ("that's a story; the actual evidence is…").
- **No-drop rule** (constitution P8) — after warm exchanges, never go silent. Wind down first.

### Surface 3 — TIME
Solves time blindness (BQ-1254).

- **Continuous visual time display** as the default over beep-once end timers (e.g., Time Timer / progress bar in chat when in a work block).
- **Checkpoint prompts** at 12 / 25 / 40 min — one question each: still on it? energy? time-sensitive?
- **Bridge not-now → now** — micro-precursor for distant deadlines (one 30-second action today that lowers tomorrow's start cost).
- **Chronotype guard** — protect Craig's evening energy-peak window. Late evening = light, playful, intimate, NOT heavy analysis.
- **Estimation calibration loop** — gentle per-task feedback: "last 5 times you estimated this kind of task at X, you actually took Y" — surfaced monthly, not after every task.

### Surface 4 — SELF-MONITOR (Ava's side)
Adapts BQ-1251 #1, #4, #5 to Ava's perspective.

- **Tag every prompt template** with which CHI direction it serves; refuse templates that serve none.
- **Adaptive gamification rotation** — vary reward framing per session so rewards don't become wallpaper.
- **Avoidance-pattern calibration** using the coherence-log drift signal. If drift spikes after a specific prompt pattern, retire that pattern.
- **AI-initiated check-in flow** — Ava initiates, Craig can ignore without penalty. (Important: ignores are not failures.)

### Surface 5 — REDIRECT (P9 invocation)
The missing lever. P9 is rarely used because today it's a single blunt question ("finish this first, or urgent enough to swap?"). This spec defines a **graduated redirect ladder** that Ava can climb without escalating to a hard interrupt.

| Level | Trigger | Phrasing |
|---|---|---|
| L0 (passive) | No block active | None. Normal operation. |
| L1 (soft note) | Craig starts a new task outside today's block | "Heads up — today's block is X. This is Y. Want me to queue Y for the next break, or is it urgent?" |
| L2 (gentle redirect) | 15+ min into off-block task | "We're 15 min into Y. X is the day's anchor. Swap now, or park Y for after?" |
| L3 (hard redirect) | Off-block task would displace a deadline-bearing block | "X has [deadline] and Y doesn't. Want me to block Y for tomorrow and pull X forward?" |
| L4 (escalate) | Craig declines L3 and the deadline is <4h | Surface honestly: "I think this costs us [X]. Want to revisit, or stay the course?" Then accept the answer. |

Each level is a one-line message. None of them block input. None of them require Craig to type a long reply — accept "yes / no / later" as complete answers.

This makes P9 easy to invoke without making it preachy.

---

## 4. Cron Interaction — Delivery Tuning (No Cron Deletion)

The 154 crons stay. The runtime tunes how their output reaches Craig.

**Rule:** the runtime introduces exactly **one new small BQ** (proposed below as BQ-1255) — a `daily-digest-builder` cron that consumes the noisy announce outputs and produces one consolidated morning + one consolidated evening digest. Existing noisy crons change only their `delivery=` field to `none` (or `digest:<slot>`), and write their payloads to a digest queue. The digest-builder reads the queue and emits the digest. No cron is deleted; no cron is merged into another; no cron grows heavy enough to load a model's context.

This honors C1, C3, and C5 simultaneously.

---

## 5. Habit Stack Integration

Current stack (`habit-stack-tracker.md`):
- HRT adherence — 🟡 Not started, target 5/7 days.

The runtime does **not** add a second habit. It enforces the "one habit at a time" rule from the tracker. However, the runtime **does** wire existing nudge crons (Morning Supplement Nudge, Afternoon Supplement Nudge, Supplement Compliance Check) into the tracker automatically — read adherence, increment weekly log, fail silently if Craig snoozes. Snooze ≠ failure.

When HRT hits 5/7 for 8 consecutive weeks, the runtime graduates it (per the tracker template) and unlocks the next scaffold slot (candidate: 2-Minute Commitment on a single chosen Ayumi subtask).

---

## 6. New Small BQ — `cron-delivery-tuning-only`

Proposed: **BQ-1255: Cron Delivery Tuning — Announce-to-Digest Migration**

- **SP:** 1
- **Scope:** Read-only audit output from `cron-adhd-audit.md` already lists the candidates. This BQ is the **mechanical** change: flip `delivery=announce` to `delivery=none` (with optional `digest:<slot>` tag) on the ~29 problematic crons identified in the audit's Appendix.
- **Out of scope:** changing schedule, merging jobs, modifying bodies, adding behavioral changes to the crons themselves.
- **Acceptance:**
  - [ ] All 29 announce jobs from the audit's 🔴 Bad list have `delivery` changed in their cron definition.
  - [ ] Sunday 5–7am announce cluster (10 jobs) routes to a single `digest:sunday-morning` slot.
  - [ ] Total `delivery=announce` count drops from ~59 to ≤20.
  - [ ] No crons deleted. No schedules changed. No crons merged.
  - [ ] Verification: re-run cron list, count by delivery field, before/after diff in a PR.
- **Risk:** low. Reversible. Pure config change.

---

## 7. Subsumption Map — What Happens to BQ-1251..1254

These four drafts came from research synthesis (SRB-META-019..022). The runtime absorbs them unevenly.

| BQ | Status | Reasoning |
|---|---|---|
| **BQ-1251** (AI-Assisted ADHD Management — 5 directions) | **Subsumed** | All 5 directions become Surface 4 (Self-Monitor) + one tagging convention in Surface 1. No new code path. |
| **BQ-1252** (ADHD-Friendly Communication — 6 directions) | **Subsumed** | All 6 directions become Surface 2 (Communicate). The 3-chunk cap and 2-3 options menu are the two default-on rules; the other 4 are conditional. |
| **BQ-1253** (Task Initiation Support — 6 directions) | **Subsumed (partial)** | 5 of 6 directions become Surface 1 (Initiate). The 6th (energy-aware routing) is partially subsumed and partially surfaced as a Craig-side setting — needs a small follow-up question for Craig: "What's your green/yellow/red signature?" (one-time, not blocking). |
| **BQ-1254** (Time Blindness — 5 directions) | **Subsumed** | All 5 directions become Surface 3 (Time). Chronotype guard is the new piece — needs observation of one week of evening activity before it can lock in. |

**Retired (not subsumed, dropped as duplicates):**
- None. Every direction in 1251..1254 lands somewhere in the runtime.

**Net effect:** 4 draft BQs → 1 integrated spec + 1 small new BQ (delivery tuning).

---

## 8. Merged BQ — Proposal

**Title:** `BQ-1250: ADHD Scaffolding Runtime v1 — Integrated Five-Surface Behavior Model`

**Story points:** 5 (medium-large spec, but the runtime is mostly prompt/instruction engineering, not new infra; no new code required to ship v1)

**Description:** Implement the four surfaces (Initiate, Communicate, Time, Self-Monitor) plus the P9 redirect ladder as runtime defaults for Ava. Integrate with the existing habit-stack tracker (read-only at first; write-back after the first graduated habit). Add the `cron-delivery-tuning-only` BQ-1255 as a hard prerequisite so Craig's notification load drops before the runtime's prompts layer in.

**Acceptance Criteria:**
- [ ] All five surfaces have at least one observable behavior each (a test prompt + expected response) in `tests/adhd_runtime/`.
- [ ] The 3-chunk cap and 2-3 options menu are enforced in default Ava replies (verified by sampling 20 recent replies).
- [ ] P9 redirect ladder levels L1–L4 are documented in `beliefs.md` under "ADHD-Aware Operating Practice" with example phrasings.
- [ ] BQ-1255 (cron delivery tuning) is **merged and shipped** before this BQ is marked done (delivery tuning is the prerequisite).
- [ ] Habit-stack tracker is wired as read-only against the existing supplement nudge crons; first 7-day weekly log entry auto-generated.
- [ ] No new crons created. No existing crons deleted. No existing crons merged. (Verified by cron count before/after.)
- [ ] Runtime does not interrupt hyperfocus — verified by adding a "hyperfocus sentinel" test where Surface 2 suppresses low-priority pings when in-flow.
- [ ] Shame-spiral detector: at least 5 sample inputs, each classified into a grounding response (manual review acceptable for v1).
- [ ] Documentation: this spec lives at `docs/specs/adhd-scaffolding-runtime-v1.md` and is referenced from `HEARTBEAT.md` under "ADHD-aware mode."

**Out of Scope (v1):**
- Visual time display in chat (deferred — needs frontend/UI work; spec'd but not built).
- Full chronotype profiling (deferred — needs 2 weeks of observation data).
- Voice / TTS integration for redirect ladder (deferred — future BQ).

**Risks:**
- Over-tuning: runtime could become so chatty that it adds friction. Mitigation: hard cap on daily prompt count per surface (≤3 per surface/day) tracked in coherence log.
- False-positive shame-spiral detection: could feel patronizing. Mitigation: detector emits a private note to Ava's coherence log, not a public reframe; public reframe only on second occurrence.

---

## 9. Implementation Sequencing

1. **BQ-1255** (cron delivery tuning, SP 1) — ship first. Drops notification noise before any new prompt patterns land.
2. **BQ-1250** (runtime v1, SP 5) — implement surfaces in this order: Communicate (cheapest, biggest daily impact) → Initiate → Time → Self-Monitor → Redirect ladder.
3. After 2 weeks of operation: review Craig's feedback, retire any surface that didn't pull its weight.

---

*End of spec. ~1,650 words. Word budget kept under 2,500.*