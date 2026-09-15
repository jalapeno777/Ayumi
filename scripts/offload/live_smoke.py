#!/usr/bin/env python3
"""Live-wire smoke dispatcher for c3134271.

Gateway-side helper that drives the smoke push via the real
``OpenClawNodeBundleTransport`` and prints a single JSON line to stdout
that the agent (Tsubaki) consumes to plan the worker-side exec flow::

    {"worker_path": "/tmp/openclaw-terminal-upload-<rand>/smoke_fixture.py",
     "bundle_sha": "...",
     "size": ...,
     "run_id": "..."}

The agent then uses ``exec(host=node, node=ava-worker-local)`` to:
    1. mkdir the per-cell scratch dirs on the worker
    2. python3 <worker_path> for each cell (writes output.json on worker)
    3. cat each output.json back through exec stdout
    4. compute output_hash on gateway + write Manifest

Why a helper rather than inline ``python3 -c`` invocation?
- Multi-cell runs idempotent and re-runnable for verification
- ``--run-id`` is the canonical run_id that ties the manifests together
- Failure surfaces as ``WorktreeUnreachableError`` from the transport,
  which is the correct error type for a node-down condition

The runner subprocess on the gateway cannot reach the worker shell
(``system.run`` is reserved-for-shell on this gateway version); this
helper is intentionally file-push only and leaves execution to the
agent-driven path documented in scripts/offload/transport.py.

DELEG-REF: c3134271-601e-42c2-9797-6407ae25048c
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="live_smoke_dispatch",
        description=(
            "Push the live-smoke fixture to ava-worker-local via the real "
            "OpenClawNodeBundleTransport. Returns a single JSON line on "
            "stdout naming the worker-side path the agent must exec via "
            "host=node."
        ),
    )
    parser.add_argument("--run-id", required=True, help="Cell run identifier")
    parser.add_argument(
        "--fixture",
        default="scripts/offload/smoke_fixture.py",
        help="Path (gateway-side) to the smoke fixture Python file",
    )
    parser.add_argument(
        "--node", default="ava-worker-local",
        help="OpenClaw node name (default: ava-worker-local)",
    )
    parser.add_argument(
        "--smoke-matrix",
        choices=["smoke"], default="smoke",
        help="Which matrix to smoke (default: smoke = the 2-cell v1 spec)",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    fixture_path = (repo_root / args.fixture).resolve()
    if not fixture_path.is_file():
        print(f"fixture not found at {fixture_path}", file=sys.stderr)
        return 2

    # Make ``offload.*`` importable when invoked as a script.
    sys.path.insert(0, str(repo_root / "scripts"))
    from offload.seed import cell_id as _derive_cell_id  # noqa: E402
    from offload.transport import (  # noqa: E402
        BundleTransportError,
        OpenClawNodeBundleTransport,
    )

    bundle_sha = hashlib.sha256(fixture_path.read_bytes()).hexdigest()

    try:
        transport = OpenClawNodeBundleTransport(node=args.node)
        cell = transport.push_bundle(args.run_id, fixture_path, bundle_sha)
    except BundleTransportError as exc:
        print(
            json.dumps({
                "ok": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }),
            file=sys.stderr,
        )
        return 3

    # Build a structured plan the agent follows for execution + fetch.
    smoke_cells = [
        ("q1_mw_formation", "GBPUSD", "M5"),
        ("q1_mw_formation", "GBPUSD", "M15"),
    ]
    plan = {
        "ok": True,
        "run_id": args.run_id,
        "node": args.node,
        "fixture_worker_path": cell.path,
        "fixture_bundle_sha": cell.sha256,
        "fixture_size_bytes": fixture_path.stat().st_size,
        "worker_scratch_root": f"/tmp/ayumi-offload/{args.run_id}",
        "cells": [
            {
                "cell_id": _derive_cell_id(*c),
                "strategy": c[0],
                "symbol": c[1],
                "timeframe": c[2],
                "output_path": f"/tmp/ayumi-offload/{args.run_id}/{_derive_cell_id(*c)}/output.json",
            }
            for c in smoke_cells
        ],
    }
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
