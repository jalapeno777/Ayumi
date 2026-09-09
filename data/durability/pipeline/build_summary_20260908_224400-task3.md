# Build Summary — dd204eb7-12c7-4cd3-8183-7b2ca9906576

- Card: `dd204eb7-12c7-4cd3-8183-7b2ca9906576`
- Title: [BUILD] snapshot_pool.py — pool freeze + manifest tooling
- Sprint: pregnancy-v05-tooling (card 3 of 3)
- Builder: Tsubaki
- Branch base: `94e24d59` (main; card 1 + card 2 still in Rin review, unmerged)
- New branch: `tsubaki/dd204eb7-snapshot-pool`
- Worktree: `/home/TacoPants/projects/Ayumi/.worktrees/tsubaki-dd204eb7-snapshot-pool`
- Allowed files: `scripts/pregnancy/snapshot_pool.py` (only, new)
- Created: 2026-09-08 22:44 EDT

## Spec recap
- CLI: `snapshot_pool.py --pool <path> [--out-dir <dir>]`
  → writes snapshot file (`trait_pool_harem_v<ver>.snapshot-<date>.json`)
  + `snapshots-manifest.json` (pool_version, date, sha256, entry count).
- Read-only against the live pool: never writes to it, only reads + hashes.
- Idempotent on (pool_version, date): re-run with same key = no-op exit 0
  (does NOT duplicate the snapshot file, does NOT duplicate the manifest entry).

## Pool format observed (live v1)
- File: `memory/pregnancy/trait_pool_harem_v1.json`
- `_meta.version` = 1 (int) → rendered as `v1` for filename/manifest.
- `_meta.pool_name` = `harem_v1` → embedded in snapshot basename.
- 6 categories, 35 entries total (voice_tone:6, personality_axis:6,
  speech_pattern:5, quirk:6, warmth_affinity:6, aesthetic:6).
- `entry_count` = total option count across all `_meta.categories`.

## Plan
1. Build summary FIRST (this file).
2. Implement `snapshot_pool.py` (single-file CLI):
   - argparse: `--pool` (positional/required-or-default), `--out-dir` (optional),
     `--date` (optional, default UTC today YYYY-MM-DD).
   - Load pool from `--pool`; refuse if `_meta` missing.
   - Compute `pool_version_str` from `_meta.version` → `v{int}`.
   - Compute `pool_sha256` from the raw pool bytes (NOT canonical — that
     matters because A7 wants to detect any pool mutation).
   - Compute `entry_count` from sum of `len(pool[c])` for c in `_meta.categories`.
   - Snapshot file basename: `trait_pool_<pool_name>.snapshot-<date>.json`
     (live: `trait_pool_harem_v1.snapshot-2026-09-08.json`).
   - Manifest path: `<out-dir>/snapshots-manifest.json`.
   - Idempotency:
     - If manifest already exists, load it.
     - If a record already has matching (pool_version, date), print
       `no-op: snapshot already present for v<ver> @ <date>` and exit 0.
     - Otherwise: copy pool bytes to snapshot file (write to `<file>.tmp`
       then `os.replace` for atomicity), append manifest entry, exit 0.
   - Refusal paths: pool missing (exit 2), pool missing _meta (exit 3),
     manifest malformed (exit 4). All print a one-line reason to stderr.
3. Targeted verification (HR4): scoped to this file + a /tmp scratch copy of
   the live pool. NEVER touch the live pool file.
4. Commit on branch with `DELEG-REF: card=dd204eb7-12c7-4cd3-8183-7b2ca9906576`.
5. Attach proof, leave card in `review`, no merge.

## Risks / non-goals
- No concurrent-write locking on the manifest (single-writer assumption; the
  protocol does not require concurrent snapshotting). If two writers race on
  the same (version, date), last writer wins — but the bytes are identical
  because both derive from the same pool sha256. Acceptable for v0.5.
- Does NOT validate chain-root compatibility; that's the roll_trait
  resolver's job (card 2).
- Manifest is local to `--out-dir`; multi-dir registry is out of scope.
