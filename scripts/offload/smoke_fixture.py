#!/usr/bin/env python3
"""Smoke fixture for c3134271 live 2-cell wire smoke (AC #2).

This module is the worker-side executable that proves the wire works
end-to-end: it parses ``--strategy / --symbol / --timeframe`` from
``sys.argv``, computes deterministic stub metrics (no DuckDB
dependency — keeps the worker setup scope narrow for c3134271),
and writes ``output.json`` to the path supplied via ``--output``.

It is the c3134271 stand-in for the real strategy execution that the
matrix card (05fa0065) will eventually drive on the worker; the wire
contract (push → execute → fetch → hash) is what this fixture validates.

Output JSON schema mirrors the offload scorecard schema (deliberately
so — the runner's ``Manifest.from_dict`` deserialization treats it as
opaque bytes and computes ``output_hash`` from them).

Usage on the worker::

    python3 smoke_fixture.py --strategy q1_mw_formation \\
        --symbol GBPUSD --timeframe M5 \\
        --output /tmp/ayumi-offload/<run_id>/<cell_id>/output.json

DELEG-REF: c3134271-601e-42c2-9797-6407ae25048c
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _argv_to_dict(argv: list[str]) -> dict[str, str]:
    """Tiny ``--key VALUE`` parser; keeps the fixture module-pure
    (no argparse bloat for ~5 flags).
    """
    out: dict[str, str] = {}
    it = iter(argv)
    for tok in it:
        if tok.startswith("--") and tok in {"--strategy", "--symbol", "--timeframe", "--output"}:
            try:
                out[tok] = next(it)
            except StopIteration:
                pass
    return out


def _cell_id(strategy: str, symbol: str, timeframe: str) -> str:
    """Same Q4 v1 binding as ``offload.seed.cell_id`` (16-hex first slice)."""
    payload = f"{strategy}|{symbol}|{timeframe}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    args = _argv_to_dict(argv if argv is not None else sys.argv[1:])

    strategy = args.get("--strategy", "")
    symbol = args.get("--symbol", "")
    timeframe = args.get("--timeframe", "")
    output_path = Path(args.get("--output", "/tmp/ayumi-offload/output.json"))

    if not (strategy and symbol and timeframe):
        print(
            f"smoke_fixture: missing required --strategy / --symbol / --timeframe "
            f"(got {args!r})",
            file=sys.stderr,
        )
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cid = _cell_id(strategy, symbol, timeframe)
    digest = hashlib.sha256(cid.encode("utf-8")).digest()

    metrics = {
        "n_trades": 50 + (digest[0] % 50),                # 50..99
        "net_pips": round((digest[1] - digest[2]) * 0.5, 2),
        "win_rate": round(0.40 + (digest[3] / 255) * 0.20, 4),
        "sharpe": round((digest[4] - 128) / 50.0, 3),
        "max_dd_pips": round(-(digest[5] / 255) * 30, 1),
    }

    now_iso = datetime.now(timezone.utc).isoformat()
    scorecard = {
        "cell_id": cid,
        "seed": cid,
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "metrics": metrics,
        "started_at": now_iso,
        "finished_at": now_iso,
        # Smoke proof artifacts: NOT local fallback. Markers explicitly
        # signal that computation happened on the worker.
        "local_fallback": False,
        "remote_execution": True,
        "worker_node": os.environ.get("AYUMI_WORKER_NODE", "ava-worker-local"),
        "worker_hostname": os.uname().nodename,
        "v1_stub": False,
    }

    output_path.write_text(json.dumps(scorecard, indent=2, sort_keys=True))
    size = output_path.stat().st_size
    print(
        f"smoke_fixture: wrote {output_path} ({size} bytes) "
        f"for {strategy}/{symbol}/{timeframe} cell_id={cid}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
