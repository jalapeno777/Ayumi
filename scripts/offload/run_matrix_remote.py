#!/usr/bin/env python3
"""Ayumi node-offload runner v1 — CLI dispatch loop (Q1+Q4+Q6).

Per card f9414fe1 + Tomoe brief: thin wrapper over OpenClaw node
transport (system.run + file transfer). v1 ships with a
Port8877StubTransport which raises on real invoke, driving the
local-fallback path. The BundleTransport ABC stays the contract —
a terminal.upload impl slots in when gateway 9.5 lands.

This is the cycle-2 dispatch skeleton. Cycle-1 helper modules
(manifest, transport, seed) are wired here:

- atomic_write_manifest() + per_cell_lock(): called per cell (Q4.b/c)
- lock_files_hash(): captured once at dispatch time (Q3)
- BundleTransport.push_bundle(): wrapped in try/except (Q1 skew ABORT,
  Q2 unreachable → local-fallback flag)
- Manifest dataclass: extended with bundle_files (Tomoe watch item 1)

CPU-first v1; GPU deferred (card AC5 out-of-scope). No touch to live
ayumi-forward-test service.

Deferred to subsequent cycles:
- cycle 3 — dispatch_skipped.py jsonl appender; scoring.py real local
  fallback execution; --resume skip logic
- cycle 4 — tests/offload/* (AC extensions, parallel-resume, DB-skip,
  forced-skew)
- cycle 5 — README.md (Tomoe watch item 2 wording on local-fallback honesty)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

# Allow running this script directly (python3 scripts/offload/run_matrix_remote.py)
# without requiring `-m offload.run_matrix_remote`. One sys.path mutation at
# module-load time; benefit is the simpler user-facing invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offload.manifest import (
    Manifest,
    atomic_write_manifest,
    per_cell_lock,
)
from offload.seed import cell_id, lock_files_hash
from offload.transport import (
    BundleTransport,
    BundleTransportError,
    CodeSHARejectedError,
    Port8877StubTransport,
)


# v1 default output_root base (Q6(a) CLI > env > default). Subdir layout
# (e.g. {manifests,scorecards,logs}/) deferred to cycle 3.
DEFAULT_OUTPUT_ROOT = "data/offload"


# v1 smoke matrix — 1 strategy × 1 symbol × 2 TFs (card AC1 spec).
# Future impl: parse a matrix spec file (JSON/YAML); v1 ships inline.
SMOKE_MATRIX: list[tuple[str, str, str]] = [
    ("q1_mw_formation", "GBPUSD", "M5"),
    ("q1_mw_formation", "GBPUSD", "M15"),
]


def _resolve_output_root(cli_root: str | None, repo_root: Path) -> Path:
    """--output-root precedence: CLI flag > $AYUMI_OFFLOAD_ROOT env > default (Q6)."""
    explicit = cli_root or os.environ.get("AYUMI_OFFLOAD_ROOT")
    if explicit:
        return Path(explicit)
    return repo_root / DEFAULT_OUTPUT_ROOT


def _current_git_sha(repo_root: Path) -> str:
    """Pin dispatcher-side git_sha at dispatch time (Q4.e two-SHA split)."""
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _bundle_path(repo_root: Path) -> Path:
    """Local source dir we hand to the worker via push-bundle (Q2)."""
    return repo_root / "scripts" / "offload"


def _bundle_sha_and_files(bundle_path: Path) -> tuple[str, list[str]]:
    """SHA256 + filename list of the bundle (Tomoe watch item 1).

    sorted() keeps the SHA deterministic across filesystems and runs.
    ``__pycache__/`` is excluded — bytecode is a build artifact, not
    source; including it would cause spurious bundle drift across runs
    (mtime + platform-specific bytecode headers).
    """
    h = hashlib.sha256()
    names: list[str] = []
    if not bundle_path.is_dir():
        return h.hexdigest(), names
    for p in sorted(bundle_path.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(bundle_path)
        if any(part == "__pycache__" for part in rel.parts):
            continue
        names.append(str(rel))
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest(), names


def _run_one_cell(
    *,
    strategy: str,
    symbol: str,
    timeframe: str,
    args: argparse.Namespace,
    transport: BundleTransport,
    output_root: Path,
    git_sha: str,
    env_lock_hash_val: str,
    env_lock_files_names: list[str],
    bundle_path: Path,
    bundle_sha: str,
    bundle_files: list[str],
) -> Manifest:
    """Dispatch one cell; returns the atomic-written manifest.

    Q1 skew raises CodeSHARejectedError (loud ABORT, never fallback).
    Q2 WorktreeUnreachableError + other BundleTransportError → set
    local_fallback=True and continue (Q7: same schema, observability only).
    """
    cid = cell_id(strategy, symbol, timeframe)
    cell_out = output_root / cid

    with per_cell_lock(cell_out):
        m = Manifest(
            cell_id=cid,
            seed=cid,                    # Q4 v1: cell_id == seed (binding)
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            git_sha=git_sha,
            env_lock_hash=env_lock_hash_val,
            env_lock_files=env_lock_files_names,
            bundle_files=bundle_files,   # Tomoe watch item 1
            db_sha=None,
            local_fallback=False,
        )

        try:
            transport.push_bundle(args.run_id, bundle_path, bundle_sha)
        except CodeSHARejectedError:
            # Q1 loud skew: ABORT, never fallback.
            raise
        except BundleTransportError:
            # WorktreeUnreachableError + everything else → local fallback (Q7).
            m.local_fallback = True

    atomic_write_manifest(m, cell_out)  # Q4.b POSIX-atomic
    return m


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_matrix_remote",
        description=(
            "Ayumi node-offload runner v1 — dispatches backtest/tournament "
            "matrix cells to ava-worker (CPU-first; GPU deferred). v1 ships "
            "with local-fallback path; BundleTransport ABC is wired so a "
            "terminal.upload impl slots in when gateway 9.5 lands."
        ),
    )
    parser.add_argument("--matrix", choices=["smoke"], default="smoke")
    parser.add_argument("--run-id", default="v1smoke")
    parser.add_argument(
        "--output-root", default=None,
        help=(
            "Dispatcher-side root for manifests + scorecards. Precedence: "
            "this flag > $AYUMI_OFFLOAD_ROOT env > <repo>/data/offload/<run-id>/."
        ),
    )
    parser.add_argument(
        "--resume", action="store_true",
        help=argparse.SUPPRESS,  # cycle 3 will populate
    )
    parser.add_argument("--worker", default="ava-worker-local")
    parser.add_argument(
        "--simulate-transport", action="store_true",
        help="Use Port8877StubTransport.simulate_success=True (ABC contract tests).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    output_root = _resolve_output_root(args.output_root, repo_root) / args.run_id

    env_lock_hash_val, env_lock_files_names = lock_files_hash(repo_root)
    git_sha = _current_git_sha(repo_root)
    bundle_path = _bundle_path(repo_root)
    bundle_sha, bundle_files = _bundle_sha_and_files(bundle_path)

    transport: BundleTransport = (
        Port8877StubTransport(simulate_success=True)
        if args.simulate_transport
        else Port8877StubTransport()  # raises on real invoke → drives local fallback
    )

    manifests: list[Manifest] = []
    for strategy, symbol, timeframe in SMOKE_MATRIX:
        m = _run_one_cell(
            strategy=strategy,
            symbol=symbol,
            timeframe=timeframe,
            args=args,
            transport=transport,
            output_root=output_root,
            git_sha=git_sha,
            env_lock_hash_val=env_lock_hash_val,
            env_lock_files_names=env_lock_files_names,
            bundle_path=bundle_path,
            bundle_sha=bundle_sha,
            bundle_files=bundle_files,
        )
        manifests.append(m)

    # CLI summary (Q7 — observability; never silent).
    n_total = len(manifests)
    n_local = sum(1 for m in manifests if m.local_fallback)
    if n_local:
        print(f"{n_total}/{n_total} cells: local fallback (worker unreachable)")
    else:
        print(f"{n_total}/{n_total} cells: dispatched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
