# Deadline Owner-Tag Contract

**Card:** 0b910897-2e60-4556-83d5-e5abd051e505
**Effective:** 2026-09-07
**Owner of contract:** build lane (Tsubaki)
**Approver:** Rin (review)

## Why this exists

Sprint and plan docs accumulated advisory deadlines — dates that no one
felt individually responsible for hitting. The failure mode showed up as the
"Cabal Aug-10" advisory slip and the "briefing-pack Aug-11" advisory slip:
each date lived in the doc, but no enforcement owned it. From the day
this contract lands, **every date in a plan must carry an owner tag, or it
is stripped at plan time.**

## Contract

| Tag            | Meaning                                                                                  | Missed-slot consequence                                          |
| -------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `CRAIG-OWNED`  | Lives on a calendar surface slot that a named human (currently Craig) must hit.         | After 2 misses → auto-converts to `AGENT-OWNED` with default action (see below). |
| `AGENT-OWNED`  | The date is enforced by automation; no human action required at the slot boundary.       | Surfaced in the next heartbeat sweep; agent lane runs the default action. |

A date with neither tag is **untagged**. At plan time:

1. `scripts/validate_sprint_plan.sh <sprint-id> phase3 --doc <plan>` exits
   non-zero with a stderr listing every untagged date and line number.
2. With `--strip`, `scripts/deadline_owner_check.py` rewrites the doc and
   reports each removal to stderr.

Tag markers may appear in plain text, in backticks, or in square brackets
on the same logical line as the date:

```
[CRAIG-OWNED] 2026-09-15  — Cabal briefing sign-off
`AGENT-OWNED` 2026-09-22 — quarterly owner-tag sweep runs itself
```

## Missed-slot rule

`CRAIG-OWNED` slot missed twice → auto-converts to `AGENT-OWNED` with the
default action for that class of deadline. Default actions per class:

| Deadline class       | Default action on `CRAIG-OWNED` → `AGENT-OWNED` conversion       |
| -------------------- | --------------------------------------------------------------- |
| Sprint sign-off      | Push the sprint to `review` state; Rin is paged.                |
| Briefing pack        | Generate the pack from the latest sprint doc + ship to the cron-channel. |
| Calendar surface slot| Drop the slot; reschedule via the next lane-planning heartbeat.  |

Conversion is **one-way**. Once a deadline has been demoted by the missed-slot
rule, no path promotes it back to `CRAIG-OWNED` without an explicit ADR.

## Two-week shadow count (baseline, 2026-09-07)

`scripts/deadline_owner_check.py --baseline` was run against every
sprint/plan doc on disk that the scanner is wired to handle today:

```
$ for f in data/sprint-plans/*.md data/sprints/*.md docs/decisions/ARCHIVED/sprint-plans/*.md; do
    python3 scripts/deadline_owner_check.py --baseline "$f"
  done | python3 -c "..."

totals: 123 dates scanned, 123 untagged (100%).
```

| Doc                                                | Dates | Untagged |
| -------------------------------------------------- | ----: | -------: |
| `data/sprint-plans/ayumi-historical-mypy-claims-audit.md` | 114 | 114 |
| `data/sprints/s008-w3b-f401-adjudication.md`              |   3 |   3 |
| `data/sprints/s008-w4b-s101-adjudication.md`              |   6 |   6 |
| `docs/decisions/ARCHIVED/sprint-plans/*.md` (8 files)     |   0 |   0 |

Observations:

* The entire backlog is currently 100% untagged. None of the dates in the
  sampled docs are followed by a `CRAIG-OWNED` / `AGENT-OWNED` marker — the
  tag pattern has never been used in Ayumi.
* The historical mypy audit is the largest single source of untagged dates
  (114). Most of those are version timestamps in evidence citations
  (`mtime 2026-07-10 12:13 UTC`), not deadlines; the migration plan below
  treats them as suppressable rather than requiring explicit tags.
* The two adjudication docs (`s008-w3b-f401-adjudication.md` and
  `s008-w4b-s101-adjudication.md`) carry 9 untagged dates between them;
  those are the real deadlines to triage in the first migration pass.

## Migration plan

1. **Stop-the-bleed (now):** `scripts/validate_sprint_plan.sh` phase3 is
   wired into new-card admission via card 0b910897. New sprint docs that
   pass phase3 must contain no untagged dates.
2. **First-pass triage (next 7 days):** backfill tags on the 9 real
   deadlines in `data/sprints/s008-*.md`. Suggested mapping is recorded in
   the card comment thread on 0b910897.
3. **Historical suppress (next 14 days):** annotate version-timestamp
   matches in `data/sprint-plans/ayumi-historical-mypy-claims-audit.md`
   either with `[historical-ref]` markers (excluded by the scanner via
   false-positive suppression) or with explicit `AGENT-OWNED` tags if the
   date is itself a deadline.
4. **Re-measure (day 14):** re-run the baseline loop and post the new
   numbers to this section. Target: 0 untagged dates that are real
   deadlines, with version-timestamp suppressions limited to non-deadline
   contexts.

## How to invoke

```bash
# Scan a single doc; exit 1 with a per-line report if any untagged dates:
python3 scripts/deadline_owner_check.py path/to/sprint.md

# Strip untagged dates from a doc, writing the cleaned copy to stdout:
python3 scripts/deadline_owner_check.py --strip path/to/sprint.md > cleaned.md

# In-place rewrite (use with care — the original is overwritten):
python3 scripts/deadline_owner_check.py --in-place --strip path/to/sprint.md

# Phase-gate a sprint plan (phase3 = deadline-owner contract):
bash scripts/validate_sprint_plan.sh <sprint-id> phase3 --doc <plan.md>
# exit 0 → all dates tagged, plan passes
# exit 1 → at least one untagged date; the doc must be fixed
```

## Acceptance evidence

* `python3 -m py_compile scripts/deadline_owner_check.py` exits 0.
* `bash -n scripts/validate_sprint_plan.sh` exits 0.
* `python3 scripts/deadline_owner_check.py --json fixtures/sprint-with-untagged-date.md`
  exits 1 and reports the untagged date.
* `python3 scripts/deadline_owner_check.py --json fixtures/sprint-with-tags.md`
  exits 0 and reports every date as tagged.
* `bash scripts/validate_sprint_plan.sh fixture-sprint phase3 --doc fixtures/sprint-with-untagged-date.md`
  exits non-zero; the equivalent fixture with tags exits 0.

(Fixtures live alongside the contract, ready for `git`-stage and CI wiring
once Ayumi's CI surface is restored.)

## Out of scope

This contract does **not**:

* Edit identity files, governance, or lane rules.
* Touch Ayumi's runtime code under `src/forex-bot/`.
* Backfill historical plan docs (the 14-day migration sweep handles those
  separately).
* Change the card-admission gate itself — that lives in Himari/AVA lane.