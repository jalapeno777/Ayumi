# Ayumi node-offload runner v1

Thin CLI wrapper over the OpenClaw node transport (`system.run` + `file transfer`) for
dispatching Ayumi backtest/tournament matrix cells to the `ava-worker-local` node.
v1 ships with a `Port8877StubTransport` that raises on real invoke, driving a
**local-fallback** execution path; the `BundleTransport` ABC stays the contract
for a future `terminal.upload` impl (post gateway 9.5).

## ⚠️ v1 emits stub scorecards — downstream MUST NOT ingest as real

> **"v1 emits stub scorecards for every cell. Real numbers return only after
> BundleTransport wires to a live port-8877 receiver (or terminal.upload
> post-9.5). The downstream consumer (card
> 05fa0065-2e96-46ee-a57b-2842d451e8df) MUST NOT ingest v1 metrics as
> real."**
>
> — Tomoe, cycle-3 sign-off (relayed via Ava, 2026-09-15)

This sentence is the blocking acceptance criterion for terminal sign-off. Every
v1 scorecard in `data/offload/<run-id>/<cell_id>/scorecard.json` carries
`"local_fallback": true` and `"v1_stub": true` flags so dashboards can
distinguish placeholders from real PnL.

## Card scope

**In scope (v1):**
- CLI dispatch loop: 2-cell smoke matrix (`run_matrix_remote.py --matrix smoke`)
- Per-cell JSON manifest with deterministic `cell_id` (= `seed`)
- Atomic two-phase manifest write (`draft.json` → `os.replace` → `manifest.json`)
- Per-cell `flock(LOCK_EX|LOCK_NB)` lock for `--resume` safety + parallel-run safety
- Q1 loud-skew rejection via `dispatch_skipped.jsonl`
- Local-fallback scorecard emission on `BundleTransportError`
- `AYUMI_OFFLOAD_ROOT` env override + `--output-root` CLI flag (Q6 flag)

**Out of scope (deferred to v2):**
- GPU wiring (RTX 5060 Ti on worker; CPU-first v1, per dispatch)
- ML confidence 1C.4 / Monte-Carlo bootstrap scoring
- Real `terminal.upload` impl (post gateway 9.5)
- Chaos / fault-injection suite (Riko card `27dea9ee-…`)
- 68-cell tournament content (Tsubaki card `05fa0065-…`)
- Live `ayumi-forward-test` service modifications

## Usage

```bash
# Default: smoke 2-cell matrix under simulate mode (v1 ships Port8877StubTransport)
python3 scripts/offload/run_matrix_remote.py \
    --run-id my-smoke \
    --simulate-transport

# Default mode (no --simulate): stub raises; runner falls back to local score
python3 scripts/offload/run_matrix_remote.py \
    --run-id my-fb

# Resume: skip cells whose terminal manifest already exists
python3 scripts/offload/run_matrix_remote.py \
    --run-id my-resume \
    --simulate-transport --resume

# Output root precedence: --output-root > $AYUMI_OFFLOAD_ROOT > <repo>/data/offload/<run-id>/
python3 scripts/offload/run_matrix_remote.py \
    --run-id my-env \
    --simulate-transport                                    # uses $AYUMI_OFFLOAD_ROOT
AYUMI_OFFLOAD_ROOT=/var/ayumi/out python3 scripts/offload/run_matrix_remote.py \
    --run-id my-other --simulate-transport                  # env wins
```

## CLI surface (`--help`)

```
usage: run_matrix_remote [-h] [--matrix {smoke}] [--run-id RUN_ID]
                         [--output-root OUTPUT_ROOT] [--resume] [--worker WORKER]
                         [--simulate-transport]
```

## Scaffold

```
scripts/offload/
├── __init__.py               # package docstring + non-goals
├── seed.py                   # cell_id == seed binding (Q4 v1); env_lock_files_names (Q3)
├── transport.py              # BundleTransport ABC + error hierarchy + Port8877Stub
├── manifest.py               # Manifest dataclass + atomic_write + per_cell_lock (Q4.b/c)
├── dispatch_skipped.py       # JSONL appender for Q1 loud skew (Q1)
├── scoring.py                # local-fallback scorecard (v1 stub; deterministic)
├── run_matrix_remote.py      # CLI dispatch loop (cycle 2/3/4a-pre)
└── README.md                 # this file
```

## Key contracts

### `cell_id == seed` (Q4 v1 binding)

Both `cell_id` and `seed` derive from the same `sha256(strategy || symbol || tf)`
first-16-hex digest. The `Manifest` dataclass carries both, and they MUST
match. v1 ships this as a deliberate constraint; v2 may split them if
needed (documented here for the v2 migration).

### Atomic manifest write (Q4.b)

Two-phase: `manifest.draft.json` (placeholder + `started_at`) → `os.replace` →
`manifest.json` (terminal). A leftover `.draft.json` is an in-flight cell
(safely re-runnable). `--resume` ignores `manifest.draft.*` and treats only
terminal `manifest.json` as authoritative.

### Per-cell lock (Q4.c)

`per_cell_lock(cell_out)` opens `manifest.lock` and applies
`fcntl.flock(LOCK_EX | LOCK_NB)`. A second holder raises `RuntimeError` (skip
with warning). `_run_one_cell` catches that and returns
`("skipped_resume", None)` — `main()` does NOT crash.

### dispatch_skipped.jsonl (Q1)

One row per `code_skew` ABORT:
```json
{"cell_id": "...", "reason": "code_skew", "expected": "<sha>",
 "actual": "<worker-side; see logs>", "ts": "<ISO-8601 UTC>",
 "git_sha": "...", "env_lock_hash": "..."}
```

flock-protected (separate `dispatch_skipped.lock`) so concurrent dispatchers
can't interleave bytes.

## Quality gate

```bash
# Canon (per Ava, 2026-09-15). NOT vendored into Ayumi.
python3 /root/.openclaw/workspace/scripts/builder_quality_gate.py \
    --git-diff --workspace "$(pwd)"
```

## Verification

```bash
# Cycle 4 + 5 test surface (52 tests, ~3s):
cd /home/TacoPants/projects/Ayumi
# Note: scripts/run_test_scope.sh does not accept raw test paths; use direct pytest.
python3 -m pytest tests/offload/ -v
```

## Open consumers (must be aware of v1 stub flag)

- Card `05fa0065-2e96-46ee-a57b-2842d451e8df` (Tsubaki, 68-cell tournament): **MUST NOT
  ingest v1 scorecard metrics as real**. Filter on `"v1_stub": true` before
  consuming any scorecard.
- Card `27dea9ee-90dc-4e01-a3b8-2531a0688771` (Riko, fault injection): reads
  `dispatch_skipped.jsonl` for skew-rejection replay. Suite lives in
  `tests/offload/test_fault_injection.py` (4 scenarios; see "Fault
  injection (chaos) suite" section below).

DELEG-REF: f9414fe1-e8f8-4723-960f-1f237287b659

## Fault injection (chaos) suite

Validates the runner's trust-boundary semantics against four fault classes
(card `27dea9ee-90dc-4e01-a3b8-2531a0688771` — pre-matrix gate per Sora's
"untested fault tolerance is no fault tolerance" directive, 2026-09-15).
Run via:

```bash
cd /home/TacoPants/projects/Ayumi
python3 -m pytest tests/offload/test_fault_injection.py -v
```

| Scenario | Test | What it proves |
|---|---|---|
| 1. Kill worker mid-job | `test_scenario1_kill_midjob_resume_only_reruns_killed_cell` | 2-cell matrix; cell B "killed" between `push_bundle` and `fetch_output` (worker `WorktreeUnreachableError`). ABORT writes `output_missing` audit row. `--resume` skips cell A (byte-identical output, transport NOT re-called) and re-executes cell B (fresh dispatch with new output bytes). |
| 2. Transport loss mid-dispatch | `test_scenario2_transport_loss_falls_back_without_audit_row` | `WorktreeUnreachableError` on `push_bundle` → local-fallback path with `local_fallback=true`, `scorecard.json` with `v1_stub=true` emitted. **`dispatch_skipped.jsonl` is NOT written** — fallback is graceful, not loud ABORT. |
| 3. Version-skew rejection | `test_scenario3_worker_sha_mismatch_writes_audit_row_and_aborts` | Worker `WorkerCell.sha256` differs from dispatcher's `bundle_sha` → `CodeSHARejectedError` raised (no fallback). `code_skew` audit row written BEFORE the raise with expected/actual SHAs. `fetch_output` is never reached. |
| 4. Poisoned-output detection | `test_scenario4_tampered_output_hash_resume_writes_audit_row` | Manifest `output_hash` tampered post-dispatch → `--resume` detects mismatch via SHA recomputation, writes `output_hash_mismatch` audit row, re-executes the cell, rewrites the manifest with the correct hash. |

### Findings (Riko, 2026-09-15)

- **v1 lacks a worker-side `env_lock_hash` check.** Card scenario 3 says
  "stale env lock on worker"; the v1 trust boundary is the bundle SHA
  mismatch (`CodeSHARejectedError`), which is what the test exercises. A
  worker-side `env_lock_hash` validator would need a worker stub capable
  of computing `env_lock_hash` locally — out of scope for the v1
  `Port8877StubTransport`. Track as a v2 follow-up.
- **Cell-level "byte-identical on skip" invariant** (scenario 1) is
  asserted via `Path(output_path).read_bytes()` round-trip across the
  resume pass — a stronger guarantee than just manifest re-parse. The
  `fresh_a.push_calls == []` and `fresh_a.fetch_calls == []` assertions
  prove the runner never re-entered the wire path for skipped cells.
- **Fallback is graceful; ABORT is loud.** The audit log distinguishes
  the two: `dispatch_skipped.jsonl` rows are reserved for ABORT-class
  faults (`code_skew`, `bundle_too_large`, `output_missing`,
  `output_hash_mismatch`, `output_path_missing`); transport-level
  unreachable errors route through the local-fallback branch and write
  no row. Scenario 2 locks this in.

DELEG-REF: 27dea9ee-90dc-4e01-a3b8-2531a0688771
