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
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running this script directly (python3 scripts/offload/run_matrix_remote.py)
# without requiring `-m offload.run_matrix_remote`. One sys.path mutation at
# module-load time; benefit is the simpler user-facing invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from offload.dispatch_skipped import append_skipped
from offload.manifest import (
    Manifest,
    atomic_write_manifest,
    per_cell_lock,
)
from offload.scoring import score_cell_local
from offload.seed import cell_id, lock_files_hash
from offload.transport import (
    BundleTooLargeError,
    BundleTransport,
    BundleTransportError,
    CodeSHARejectedError,
    OpenClawNodeBundleTransport,
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
    git_bin = shutil.which("git") or "/usr/bin/git"
    out = subprocess.run(  # noqa: S603 — args hardcoded; binary resolved via shutil.which w/ /usr/bin/git fallback (lint false positive)
        [git_bin, "rev-parse", "HEAD"],
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
    current_db_sha: str | None = None,
) -> tuple[Manifest | None, str]:
    """Dispatch one cell; returns ``(manifest | None, status)``.

    Status values:
      - ``"dispatched"``       — remote path succeeded (Q2 happy)
      - ``"local_fallback"``   — transport errored; local score emitted (Q7)
      - ``"skipped_resume"``   — ``--resume`` hit a terminal manifest (Q4.b),
                                 OR per_cell_lock contention (Q4.c)

    Q1 loud skew (``CodeSHARejectedError``) → log to dispatch_skipped.jsonl
    + ABORT (re-raises; no atomic write; nothing recorded as "skipped").

    Q4.c lock contention (``per_cell_lock`` raises ``RuntimeError``) →
    caught at the function boundary; converted to skipped_resume + stderr
    warning so ``main()`` doesn't crash on parallel ``--resume``. The
    parallel-resume test in cycle 4b reproduces + verifies the wire end
    to end. Single-cell unit of ``per_cell_lock`` raising is covered in
    ``tests/offload/test_manifest.py::test_per_cell_lock_raises_runtime_error_on_contention``.
    """
    cid = cell_id(strategy, symbol, timeframe)
    cell_out = output_root / cid

    try:
        with per_cell_lock(cell_out):  # Q4.c; raises RuntimeError on contention
            manifest_path = cell_out / "manifest.json"
            draft_path = cell_out / "manifest.draft.json"

            # --resume: skip ONLY if a terminal manifest exists AND its
            # output is verifiable + SHA matches (Rin finding #4).
            # Tampered or missing output → fall through to fresh run +
            # log an audit row (output_hash_mismatch / output_path_missing).
            if args.resume:
                if manifest_path.is_file():
                    try:
                        prior = Manifest.from_dict(
                            json.loads(manifest_path.read_text())
                        )
                        if prior.finished_at is not None:
                            skip_verified = False
                            if prior.output_path and prior.output_hash:
                                out_p = Path(prior.output_path)
                                if out_p.is_file():
                                    actual = hashlib.sha256(
                                        out_p.read_bytes()
                                    ).hexdigest()
                                    if actual == prior.output_hash:
                                        skip_verified = True
                                    else:
                                        append_skipped(
                                            output_root,
                                            cell_id=cid,
                                            reason="output_hash_mismatch",
                                            expected=prior.output_hash,
                                            actual=actual,
                                            extra={
                                                "prior_manifest": str(manifest_path),
                                            },
                                        )
                                else:
                                    append_skipped(
                                        output_root,
                                        cell_id=cid,
                                        reason="output_path_missing",
                                        expected=prior.output_path,
                                        actual="<file not found>",
                                    )
                            # else: incomplete prior (no output_path/hash)
                            # → fall through to fresh run.
                            if skip_verified:
                                return prior, "skipped_resume"
                    except (json.JSONDecodeError, KeyError):
                        pass  # corrupt prior — fall through to fresh run
                elif draft_path.is_file():
                    # In-flight per Q4.b — refuse to clobber an in-progress cell.
                    return None, "skipped_resume"

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
                db_sha=current_db_sha,
                local_fallback=False,
            )

            try:
                worker_cell = transport.push_bundle(
                    args.run_id, bundle_path, bundle_sha
                )
            except CodeSHARejectedError:
                # Q1 loud skew: log row + ABORT. Log BEFORE re-raise so the
                # audit row is on disk even though no manifest is written.
                append_skipped(
                    output_root,
                    cell_id=cid,
                    reason="code_skew",
                    expected=bundle_sha,
                    actual="<worker-side; see logs>",
                    extra={"git_sha": git_sha, "env_lock_hash": env_lock_hash_val},
                )
                raise
            except BundleTooLargeError:
                # Rin finding #1: BundleTooLargeError must FAIL LOUD, never
                # trigger local fallback (Tomoe explicit at checkpoint 2
                # sign-off). Audit row + propagate so the runner exits
                # nonzero with NO fallback manifest written.
                append_skipped(
                    output_root,
                    cell_id=cid,
                    reason="bundle_too_large",
                    expected=bundle_sha,
                    actual=None,
                    extra={"bundle_size_exceeded": "see worker logs"},
                )
                raise
            except BundleTransportError:
                # Q2 unreachable → local-fallback score + flag (Q7 observability,
                # not control flow). Same scorecard schema as the remote path.
                m.local_fallback = True
                score_path = cell_out / "scorecard.json"
                score_cell_local(
                    strategy=strategy, symbol=symbol, timeframe=timeframe,
                    seed=cid, output_path=score_path,
                )
                m.finished_at = datetime.now(timezone.utc).isoformat()
                m.exit_code = 0
                m.output_path = str(score_path)
                status = "local_fallback"
            else:
                # Fix #2 (Rin): validate the worker's reported SHA matches what
                # we sent. Trust boundary; mismatch routes through
                # CodeSHARejectedError semantics (audit row + ABORT, no
                # fallback manifest).
                if worker_cell.sha256 != bundle_sha:
                    append_skipped(
                        output_root,
                        cell_id=cid,
                        reason="code_skew",
                        expected=bundle_sha,
                        actual=worker_cell.sha256,
                        extra={
                            "validation": "post-push_bundle",
                            "git_sha": git_sha,
                            "env_lock_hash": env_lock_hash_val,
                        },
                    )
                    raise CodeSHARejectedError(
                        f"WorkerCell.sha256={worker_cell.sha256!r} != "
                        f"expected {bundle_sha!r}"
                    )

                # Fix #3 (Rin): retrieve + persist + hash the worker's output.
                # The runner's terminalize contract: every successful dispatch
                # MUST carry output_path + output_hash (AC4).
                output_bytes = transport.fetch_output(args.run_id, cid)
                if output_bytes is None:
                    append_skipped(
                        output_root,
                        cell_id=cid,
                        reason="output_missing",
                        expected="non-empty bytes",
                        actual=None,
                    )
                    raise BundleTransportError(
                        f"fetch_output returned None for cell {cid!r} after "
                        f"successful push_bundle; refusing to terminalize "
                        f"without output_hash (Rin finding #3 / AC4)"
                    )

                output_hash = hashlib.sha256(output_bytes).hexdigest()
                output_path = cell_out / "output"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(output_bytes)

                m.output_path = str(output_path)
                m.output_hash = output_hash
                m.finished_at = datetime.now(timezone.utc).isoformat()
                m.exit_code = 0
                status = "dispatched"
                status = "dispatched"

            atomic_write_manifest(m, cell_out)  # Q4.b POSIX-atomic, inside the lock
            return m, status
    except RuntimeError as exc:
        # Q4.c "skip-with-warning": a parallel --resume is mid-dispatching
        # this cell. Don't propagate (would crash main()); convert to
        # skipped_resume so the loop continues. The lost cell will be
        # retried naturally on the next --resume invocation.
        print(
            f"warn: cell {cid!r} ({strategy}/{symbol}/{timeframe}): "
            f"lock contended by another runner; skipping (Q4.c "
            f"skip-with-warning): {exc}",
            file=sys.stderr,
        )
        return None, "skipped_resume"


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
        help=(
            "Skip cells whose terminal manifest already exists at "
            "{output_root}/{cell_id}/manifest.json (Q4.b). Does NOT yet "
            "detect db_sha drift (deferred to a follow-up; for now, any "
            "existing terminal manifest is reused as-is)."
        ),
    )
    parser.add_argument("--worker", default="ava-worker-local")
    parser.add_argument(
        "--transport", choices=["stub", "node"], default="node",
        help=(
            "Which BundleTransport impl to dispatch through. "
            "'node' (default, c3134271): OpenClawNodeBundleTransport — "
            "real push/exec/fetch on the ava-worker-local node. "
            "'stub' (legacy v1): Port8877StubTransport — raises on real "
            "invoke, drives local fallback (kept for the v1.0 contract "
            "until the node wire is fully smoke-validated)."
        ),
    )
    parser.add_argument(
        "--worker-node", default="ava-worker-local",
        help="Node name for OpenClawNodeBundleTransport (default: ava-worker-local).",
    )
    parser.add_argument(
        "--simulate-transport", action="store_true",
        help=(
            "(legacy) Force Port8877StubTransport.simulate_success=True "
            "regardless of --transport. Overrides --transport=node."
        ),
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    output_root = _resolve_output_root(args.output_root, repo_root) / args.run_id

    env_lock_hash_val, env_lock_files_names = lock_files_hash(repo_root)
    git_sha = _current_git_sha(repo_root)
    bundle_path = _bundle_path(repo_root)
    bundle_sha, bundle_files = _bundle_sha_and_files(bundle_path)

    # --simulate-transport (legacy) overrides --transport; otherwise --transport picks the impl.
    if args.simulate_transport:
        transport: BundleTransport = Port8877StubTransport(simulate_success=True)
    elif args.transport == "node":
        transport = OpenClawNodeBundleTransport(node=args.worker_node)
    else:
        # 'stub' legacy path: raises on real invoke → drives local fallback.
        transport = Port8877StubTransport(simulate_success=False)

    statuses: list[str] = []
    for strategy, symbol, timeframe in SMOKE_MATRIX:
        _m, status = _run_one_cell(
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
        statuses.append(status)

    # CLI summary (Q7 — observability; never silent).
    n_total = len(statuses)
    counts: dict[str, int] = {}
    for s in statuses:
        counts[s] = counts.get(s, 0) + 1
    breakdown = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
    print(f"{n_total}/{n_total} cells: {breakdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
