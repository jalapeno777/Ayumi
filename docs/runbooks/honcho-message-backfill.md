# Honcho Message Backfill — Runbook

**Card:** b230a3a8 — Honcho message backfill script
**Sprint:** Reina Sprint 079
**Builder:** Tsubaki
**Date:** 2026-08-17

## Background

On 2026-08-15 between 19:30 UTC and 22:10 UTC, a Honcho PostgreSQL credential
rotation (`Sprint 063`) caused PG auth failures that blocked ~85 conversation
messages from being persisted to `honcho.messages`. The outage did not affect
session transcripts on disk (`agents/<agent>/sessions/*.jsonl`) — those are
written by OpenClaw's own session layer and survived intact. This runbook
describes how to recover the dropped messages by replaying them from local
transcripts.

## Spec references

- Investigation: `docs/investigations/honcho-outage-dataloss-2026-08-15.md` §5.2 + §6
- Architecture: `extensions/openclaw-honcho/dist/hooks/capture.js`
  (`extractMessages`, `flushMessages`, `lastSavedIndex` watermark)
- Honcho SDK: `extensions/opencho-honcho/node_modules/@honcho-ai/sdk/dist/`

## Algorithm (one-paragraph version)

1. Scan `agents/<agent>/sessions/*.jsonl` with mtime in
   `[2026-08-15 19:30, 2026-08-15 22:10]` UTC.
2. Filter out empty transcripts (0 message events) and Codex CLI rollouts
   (`*/codex-home/sessions/...` — different schema).
3. For each transcript, parse `type=message` events with role ∈
   `{user, assistant}` (mirrors `openclaw-honcho/extractMessages`).
4. Match each transcript to its Honcho session via
   `metadata.oc_session_id == jsonl_stem`.
5. Fetch session's `lastSavedIndex` watermark and current Honcho message count.
6. Apply gap-fill rules:
   - **INTACT** (skip): `lastSavedIndex == 0 && count == 0 && transcript empty`,
     `lastSavedIndex >= transcript.length`, or `count >= lastSavedIndex`.
     In all of these, the watermark either hasn't been touched or is consistent
     with reality — nothing for us to do.
   - **CORRUPTED** (fill gap): otherwise. Insert messages
     `[lastSavedIndex, transcript.length)` via `session.addMessages`.

   Special case: `lastSavedIndex == 0 && count == 0 && transcript.length > 0`
   is treated as **CORRUPTED** (gap fills from `transcript[0:]`). This matches
   the openclaw-honcho plugin's semantics, where `lsi == 0` means "nothing
   saved yet" — all transcript messages are gaps.
7. Insert via `session.addMessages` — Honcho's natural dedup via the
   `idempotency_key` metadata guards against double-write on retry.

## Safety gates

- **Default mode is dry-run.** No Honcho writes.
- `--apply` requires `HONCHO_BACKFILL_LIVE=1` in the environment. Live run
  is OUT of sprint per HR37 / Ava dispatch. Operator must set the env var to
  acknowledge the danger.

## Usage

### Dry run (default)

```bash
python3 scripts/ops/honcho_message_backfill.py --dry-run
```

Reports:
- `sessions_discovered` — number of JSONL files in the outage window
- `sessions_empty` — filtered (0 messages)
- `sessions_no_honcho` — no matching Honcho session found
- `sessions_watermark_intact` — watermark consistent, skipped
- `sessions_watermark_corrupted` — gap fill would apply
- `messages_missing` — sum of gap_size across all sessions
- `writes_attempted` — always 0 in dry-run mode

Per-session detail table includes agent, oc_session_id, message counts,
gap size, and skip/gap reason.

### Apply (live; out of sprint)

```bash
HONCHO_BACKFILL_LIVE=1 python3 scripts/ops/honcho_message_backfill.py --apply
```

Calls `session.addMessages` for each corrupted session in chunks of 100
(Honcho's per-request limit). Messages include:
- `peer_id`: `"owner"` for user, `f"agent-{agent_id}"` for assistant
- `content`: extracted text
- `metadata`: `idempotency_key`, `role`, `source="honcho_message_backfill"`,
  `recovered_from="hr37_outage_2026_08_15"`, `recovered_at`,
  `oc_session_id`, `oc_agent_id`, `transcript_seq`

Exits with code 1 if any writes fail (5xx, network, etc.).

### Custom paths

```bash
python3 scripts/ops/honcho_message_backfill.py \
    --agents-dir /custom/agents \
    --base-url http://honcho.example.com \
    --workspace custom-ws
```

## Verification (pre-flight)

Before running the live apply:

1. **Read the dry-run output carefully.** For each session:
   - Verify the gap size matches your expectation
   - Verify the watermark reason makes sense (corrupted vs intact)
   - Verify the messages you'd expect to see in the gap
2. **Sample-check one session.** Pick a session with a non-zero gap and
   manually verify that the transcript content matches what should have been
   in Honcho.
3. **Honcho dashboard query.** Use `agent-main` peer's session list to
   confirm `lastSavedIndex` values align with the dry-run report.

## Recovery caveats

- **Codex CLI rollouts** are deliberately skipped — different JSONL schema.
  Recovery of those messages is out of scope.
- **Tool result messages** in regular sessions are not sent to Honcho by
  the plugin (only `user` and `assistant` roles). The backfill script mirrors
  this filter.
- **The `count < lastSavedIndex` "corruption" rule** is conservative: only
  sessions with a clear cross-reference discrepancy get gap-filled. Sessions
  where `count >= lastSavedIndex` are skipped even if there are messages
  beyond the watermark — this avoids risk of accidental re-sends. The
  trade-off: a small number of genuinely-missing messages beyond an intact
  watermark will not be recovered by this script.
- **Idempotency:** Honcho's `addMessages` natural dedup on `idempotency_key`
  prevents double-write on retry. Running the script twice (after a partial
  failure) will not create duplicates.

## Post-recovery audit:

After apply mode completes successfully:

```bash
# Verify all writes succeeded (no write_errors in per_session entries):
python3 scripts/ops/honcho_message_backfill.py --dry-run
# messages_missing should drop to 0 for sessions that were corrupted.

# Spot-check via Honcho HTTP API:
curl -X POST http://127.0.0.1:8008/v3/workspaces/honcho-ava-primary/sessions/<session_id>/messages/list \
    -H "Authorization: Bearer $HONCHO_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"limit": 5, "page": 1}'
```

## Rollback

If the apply run produced bad data:

1. Identify affected sessions via the dry-run report.
2. For each affected session, query Honcho messages and delete the recovered
   ones (filter on `metadata.source == "honcho_message_backfill"`).
3. Re-run the dry-run to confirm `messages_missing` matches expectations.

There is no automated rollback; operator must inspect and selectively remove
the recovered messages.

## Files

- `scripts/ops/honcho_message_backfill.py` — the script
- `tests/ops/test_honcho_message_backfill.py` — 41 unit + integration tests
- `docs/runbooks/honcho-message-backfill.md` — this runbook

## Contact / escalation

- HR37 spec author: Ava
- Card owner: Reina (Sprint 079)
- Reviewer: Rin