# Ayumi node-offload runner

Thin CLI wrapper over the OpenClaw node transport for dispatching Ayumi
backtest/tournament matrix cells to the `ava-worker-local` node.

**Two transport implementations ship behind the `BundleTransport` ABC:**

| Transport | Status | Use case |
|---|---|---|
| `Port8877StubTransport` (v1) | raises on real invoke | **Resilience / contract tests** + legacy v1.0 paths. Drives the local-fallback scorecard path. |
| `OpenClawNodeBundleTransport` (c3134271, this build) | **Real wire** via `terminal.upload` | **Production path** for any cell that must execute on the worker (Craig directive 2026-09-15). |

Local-fallback is now a **resilience safety net, not the production default.**
The 2-cell smoke on this card has live manifests with `local_fallback=false`,
`remote_execution=true`, `worker_node="ava-worker-local"` — and the next card
(05fa0065, 68-cell matrix) MUST dispatch through the real transport, per the
matrix card's directive.

## ⚠️ Smoke-stub caveat (c3134271) — downstream MUST filter on node readiness

The c3134271 live 2-cell smoke uses a **deterministic Python fixture**
(`scripts/offload/smoke_fixture.py`) that computes stub metrics from
`cell_id` bytes — it does NOT run the real strategy engine (which depends on
DuckDB + the full Ayumi repo on the worker; that cold-sync is out of scope
for the c3134271 wire-validation card). The wire is real; the metrics are
synthetic.

Every c3134271 smoke scorecard carries:

- `"v1_stub": false` — the cell DID execute on the worker
- `"local_fallback": false` — the cell did NOT fall back to local scoring
- `"remote_execution": true` — explicit remote marker
- `"worker_node": "ava-worker-local"` — provenance
- `"worker_hostname": "<uname -n on worker>"` — provenance

The downstream consumer (card `05fa0065-2e96-46ee-a57b-2842d451e8df`,
68-cell tournament) MUST NOT ingest c3134271 smoke fixtures as real PnL.
Use the markers above (especially `local_fallback=false` + `remote_execution=true`
+ the full strategy engine's PnL model in the matrix card) to gate ingestion.
The smoke proves the **wire**; the matrix card proves the **strategy engine**
on top of that wire.

## Card scope

**In scope (this build — c3134271):**
- **`OpenClawNodeBundleTransport`** class (real wire; `terminal.upload`-based push + error-mapping)
- **CLI flag** `--transport {stub,node}` + `--worker-node <name>` in `run_matrix_remote.py`; default = `node` (v2 onward)
- **`tests/offload/test_openclaw_node_transport.py`** — 14 unit tests (mocked subprocess) + 1 live smoke (gated on `AYUMI_RUN_LIVE_NODE_TESTS=1`)
- **Live 2-cell wire smoke** (AC #2): deterministic Python fixture on the worker + agent-driven exec; manifests at `data/offload/c3134271-smoke-1/<cell_id>/manifest.json` prove `local_fallback=false + remote_execution=true + worker_node="ava-worker-local"`
- Architecturally-out-of-scope for c3134271 (see "Known limitations" below): worker-side SHA verify inside `push_bundle`, fetch_output byte retrieval (file.fetch is `NO_POLICY` for now), per-cell execution from a runner subprocess (system.run is reserved-for-shell)

**In scope (v1, delivered by card `f9414fe1-…`):**
- CLI dispatch loop: 2-cell smoke matrix (`run_matrix_remote.py --matrix smoke`)
- Per-cell JSON manifest with deterministic `cell_id` (= `seed`)
- Atomic two-phase manifest write (`draft.json` → `os.replace` → `manifest.json`)
- Per-cell `flock(LOCK_EX|LOCK_NB)` lock for `--resume` safety + parallel-run safety
- Q1 loud-skew rejection via `dispatch_skipped.jsonl`
- Local-fallback scorecard emission on `BundleTransportError`
- `AYUMI_OFFLOAD_ROOT` env override + `--output-root` CLI flag (Q6 flag)

**Out of scope (deferred to v2 / next sprint):**
- GPU wiring (RTX 5060 Ti on worker; CPU-first per dispatch)
- ML confidence 1C.4 / Monte-Carlo bootstrap scoring
- 68-cell tournament content (Tsubaki card `05fa0065-…`); currently gated on worker
  env install (Ayumi repo + DuckDB + cold-sync of 53 GB market DB)
- Port-8877 HTTP receiver transport (card AC option (b)) — alternative to the
  agent-driven exec path documented below
- file-fetch policy configuration for `ava-worker-local`
  (currently `NO_POLICY`; see Known limitations)
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
                         [--transport {stub,node}] [--worker-node WORKER_NODE]
                         [--simulate-transport]
```

Key flags (c3134271 additions):
- `--transport {stub,node}` (default: `node` post-c3134271; v1 was implicitly `stub`).
  `node` uses `OpenClawNodeBundleTransport` (real wire); `stub` retains
  the legacy `Port8877StubTransport` (raises on invoke → drives local fallback).
  Used by the v1.0 contract tests in `tests/offload/test_run_matrix_remote.py`.
- `--worker-node <name>` (default: `ava-worker-local`): OpenClaw node name
  for `OpenClawNodeBundleTransport`. Multi-node support is a documented
  future-proofing slot.
- `--simulate-transport` (legacy): override `--transport=node` and use
  `Port8877StubTransport.simulate_success=True` for tests / repros.

## Scaffold

```
scripts/offload/
├── __init__.py                # package docstring + non-goals
├── seed.py                    # cell_id == seed binding (Q4 v1); env_lock_files_names (Q3)
├── transport.py               # BundleTransport ABC + error hierarchy + Port8877Stub + OpenClawNodeBundleTransport (c3134271)
├── manifest.py                # Manifest dataclass + atomic_write + per_cell_lock (Q4.b/c)
├── dispatch_skipped.py        # JSONL appender for Q1 loud skew (Q1)
├── scoring.py                 # local-fallback scorecard (v1 stub; deterministic)
├── run_matrix_remote.py       # CLI dispatch loop (cycle 2/3/4a-pre) — supports --transport {stub,node}
├── smoke_fixture.py           # c3134271 wire-validation fixture (worker-side executable; deterministic Python, no DuckDB)
├── live_smoke.py              # c3134271 gateway-side dispatch helper (pushes smoke_fixture.py via OpenClawNodeBundleTransport)
└── README.md                  # this file
```

## Known limitations on the c3134271 wire

Probed against the live gateway (`OpenClaw 2026.9.3 fa18c65`) on 2026-09-15:

| Capability | Status | Workaround in c3134271 smoke |
|---|---|---|
| `terminal.upload` (file push TO worker) | ✅ Active | Used by `OpenClawNodeBundleTransport.push_bundle`. Validated against gateway source `daemon-BbqI59vQ.js:2744` (`name` + `contentBase64`). |
| `fs.listDir` (worker dir listing) | ✅ Active | Used implicitly by the agent for `DONE` verification. |
| `system.run` (shell exec on worker) | ⚠️ Reserved-for-shell from `openclaw nodes invoke`; only the agent's `exec(host=node)` reaches the worker shell | Smoke execution step is **agent-driven** via `exec(host=node, node=ava-worker-local)`. Production scaling requires either port-8877 (card AC option (b)) or a worker-side runner. |
| `system.run.prepare` | ⚠️ Same — reserved-for-shell | n/a (use `exec(host=node)` for prep work too) |
| `file.write` | ❌ `NO_POLICY` (file-transfer plugin deny-by-default for `ava-worker-local`) | Use `terminal.upload` instead. |
| `file.fetch` | ❌ `NO_POLICY` | `fetch_output` returns `None` with a structured stderr log; the live smoke captures worker-side output bytes via `exec(host=node) cat` + base64 round-trip. |
| `ollama.*` | ✅ Active | n/a (LLM use, not relevant to offload) |
| `mcp.tools.call.v1` | ✅ Active | n/a |
| `browser.*` | ✅ Active | n/a |
| Worker-side `env_lock_hash` compute | ⚠️ Same shell-exec gate as system.run | Worker-side env-lock verify deferred to a v2/worker-daemon build (card scenario 3 "stale env lock on worker" maps here). |

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
# Targeted suite for the offload module (HR5 — never run the full repo suite):
cd $AYUMI_ROOT
python3 -m pytest tests/offload/ -v -p no:randomly

# Optional live-wire test (gated on env var; requires paired ava-worker-local):
AYUMI_RUN_LIVE_NODE_TESTS=1 python3 -m pytest tests/offload/test_openclaw_node_transport.py::test_live_push_bundle_uploads_to_ava_worker -v
```

The default `tests/offload/` run is what the c3134271 card verification command
executes; it includes the 14 new transport tests (mocked) on top of the 56
pre-existing f9414fe1 + 27dea9ee tests.

## Live smoke (c3134271 wire validation)

The card AC #2 deliverable is a live 2-cell smoke on `ava-worker-local` with
`remote_execution=true` manifests. Procedure (re-runnable from any session):

**Step 1 — gateway-side push** (uses `OpenClawNodeBundleTransport.push_bundle`):

```bash
cd $AYUMI_ROOT
python3 scripts/offload/live_smoke.py --run-id c3134271-smoke-1 \
    --fixture scripts/offload/smoke_fixture.py
```

The helper prints a single JSON plan on stdout with the worker-side path the
fixture landed at (typically
`/tmp/openclaw-terminal-upload-<rand>/smoke_fixture.py`) and the per-cell
output paths.

**Step 2 — agent-driven worker exec** (per-cell, the agent uses `exec(host=node)`):

The gateway-side runner subprocess CANNOT shell on the worker (`system.run` is
reserved-for-shell on this gateway). Per-cell execution is therefore driven
from the agent surface. For each cell in the plan:

```bash
# All in one batch (one exec per smoke run; output captures both cells):
mkdir -p /tmp/ayumi-offload/<run_id>/<cell_id>/
python3 <worker_fixture_path> \
    --strategy <S> --symbol <Y> --timeframe <TF> \
    --output /tmp/ayumi-offload/<run_id>/<cell_id>/output.json
# Capture via cat + base64 to avoid stdout-buffering loss
base64 -w0 /tmp/ayumi-offload/<run_id>/<cell_id>/output.json
```

**Step 3 — manifest write on the gateway** (the agent computes output_hash
from the captured bytes; `local_fallback=false`, `remote_execution=true`):

```python
import base64, hashlib
from offload.manifest import Manifest
# worker_bytes = base64.b64decode(captured_b64_string)
output_hash = hashlib.sha256(worker_bytes).hexdigest()
m = Manifest(cell_id=..., seed=..., strategy=..., symbol=..., timeframe=...,
             git_sha=<dispatcher HEAD>, env_lock_hash=..., env_lock_files=...,
             bundle_files=["scripts/offload/smoke_fixture.py"], db_sha=None,
             finished_at=<now>, exit_code=0, output_path=..., output_hash=...,
             local_fallback=False)  # NEW: remote marker
# + dict-merge: worker_node, remote_execution, worker_bundle_sha, worker_fixture_path
# + atomic_write_manifest(...)
```

Captured smoke artifacts (this build, recorded 2026-09-15):

| Cell | `cell_id` | `output_hash` (sha256 of worker-side bytes) | markers |
|---|---|---|---|
| M5 (q1_mw_formation/GBPUSD/M5) | `ffbfa18c3c520041` | `60fdd6940b089ec89d0430e9df1101d3e34bb0051929275c93210fd2004edb68` | `local_fallback=false`, `remote_execution=true`, `worker_node="ava-worker-local"` |
| M15 (q1_mw_formation/GBPUSD/M15) | `4cc6cb1aad83c773` | `e2893f1c4ac84cde580bea767a39e9fa5a427d2fcdb9331c974122846a2f7897` | `local_fallback=false`, `remote_execution=true`, `worker_node="ava-worker-local"` |

Manifests at: `data/offload/c3134271-smoke-1/<cell_id>/manifest.json`
Wire trace at: `data/offload/c3134271-smoke-1/wire_trace.json`

## Open consumers (must be aware of the c3134271 smoke fixture + real-wire caveats)

- Card `05fa0065-2e96-46ee-a57b-2842d451e8df` (Tsubaki, 68-cell tournament):
  - **Production wire for the 68-cell matrix requires ONE of:**
    - **Port-8877 HTTP receiver** — card AC option (b). An ACL
      `server→avaworker:8877` already exists, but the receiver process
      itself has to be stood up on `ava-worker-local` and the dispatcher
      has to be retargeted at it.
    - **A worker-side runner** — a long-running Python process on
      `ava-worker-local` that the gateway posts jobs to (via
      `terminal.upload` of bundle + a side-channel poll) and reads
      outputs back from. Same gateway surface, different receiver.
  - **`scripts/offload/live_smoke.py`'s agent-exec path is the INTERIM
    pattern, NOT the production wire.** It's the only path from the
    current gateway `openclaw nodes invoke` surface that reaches the
    worker shell, because `system.run` and `system.run.prepare` are
    "reserved for shell execution; use the exec tool with host=node
    instead" at the gateway layer (only an agent's
    `exec(host=node, node=ava-worker-local)` actually shells on the
    worker). The smoke works because the agent stays in the dispatch
    loop; that doesn't scale to 68 cells per session, so the matrix
    card must replace this with port-8877 OR a worker-side runner
    before the 68-cell run can dispatch from `run_matrix_remote.py`
    end-to-end without a human/agent in the loop.
  - **`file.fetch` is `NO_POLICY` for `ava-worker-local` today** (gateway
    `plugins.entries.file-transfer.config.nodes` is deny-by-default).
    Even with port-8877 OR a worker-side runner in place, the matrix
    card will need that allowlist configured before
    `OpenClawNodeBundleTransport.fetch_output` returns bytes end-to-end
    without falling through to the runner's `output_missing` ABORT path.
    (See the Known-limitations table below for the full wire-state map.)
  - **Smoke-scorecard caveat** (re-stated for completeness): the
    c3134271 live smoke uses a synthetic Python fixture (no real strategy
    engine, no DuckDB). The matrix card MUST NOT ingest c3134271 smoke
    scorecards as real PnL — use the `local_fallback=false +
    remote_execution=true` markers as a STARTING condition, then VALIDATE
    with the real strategy engine before treating numbers as
    authoritative.
- Card `27dea9ee-90dc-4e01-a3b8-2531a0688771` (Riko, fault injection): reads
  `dispatch_skipped.jsonl` for skew-rejection replay. Suite lives in
  `tests/offload/test_fault_injection.py` (4 scenarios; see "Fault
  injection (chaos) suite" section below).

DELEG-REFs:
- `f9414fe1-e8f8-4723-960f-1f237287b659` — v1 runner (merged)
- `27dea9ee-90dc-4e01-a3b8-2531a0688771` — chaos suite (merged)
- `c3134271-601e-42c2-9797-6407ae25048c` — this build (the real wire)

## Fault injection (chaos) suite

Validates the runner's trust-boundary semantics against four fault classes
(card `27dea9ee-90dc-4e01-a3b8-2531a0688771` — pre-matrix gate per Sora's
"untested fault tolerance is no fault tolerance" directive, 2026-09-15).
Run via:

```bash
cd $AYUMI_ROOT
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
