"""Local-fallback scorer (v1 stub).

Per Tomoe brief §3 + §4:

- Same entry point as remote scoring; identical scorecard schema whether
  the run is remote or local (Q3 — ``No downstream code may branch on
  local_fallback``).
- v1 ships as a **deterministic stub**: synthesizes metrics from the
  cell_id hash so tests can pin values across runs. Real scoring wires
  in v2 (would wrap ``scripts/backtest_blend_harness.py`` or similar).
- ``local_fallback=true`` + ``v1_stub=true`` flags on every emitted
  scorecard make it clear the number is a placeholder, not a real PnL.

The stub itself is fast (microseconds) — the local-fallback path is
not held up by it. In v2, if the real scorecard takes minutes, the
local-fallback dispatch will block per cell; that's an acceptable
trade-off because local-fallback means the worker is unreachable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from offload.seed import cell_id as _derive_cell_id

__all__ = ["score_cell_local"]


def score_cell_local(
    *,
    strategy: str,
    symbol: str,
    timeframe: str,
    seed: str,
    output_path: Path | None = None,
) -> dict[str, object]:
    """Return (and optionally write) a deterministic synthetic scorecard.

    Args:
        strategy, symbol, timeframe, seed: cell identifiers (seed is
            Q4-bound to ``cell_id()`` of the same triple).
        output_path: when given, also write the scorecard as JSON to
            this path. Parent dirs are created. Format is identical to
            the (future) remote scorecard schema.

    Returns:
        A dict matching the remote-scorecard schema (Q3 same shape):

        ``{
            "cell_id": str,
            "seed": str,
            "strategy": str,
            "symbol": str,
            "timeframe": str,
            "metrics": {n_trades, net_pips, win_rate, sharpe, max_dd_pips},
            "started_at": ISO-8601 UTC,
            "finished_at": ISO-8601 UTC,
            "local_fallback": True,
            "v1_stub": True,
        }``

    Determinism: same (strategy, symbol, timeframe) → same hash-derived
    metrics, regardless of when/where invoked. Tests can pin exact values.
    """
    cid = _derive_cell_id(strategy, symbol, timeframe)
    digest = hashlib.sha256(cid.encode("utf-8")).digest()

    # Deterministic synthetic metrics (see brief: "Local fallback is for
    # resilience, not equivalence"). Synth range reflects plausible values
    # so dashboards don't accidentally flag "n_trades=0" as a real failure.
    metrics: dict[str, object] = {
        "n_trades": 50 + (digest[0] % 50),       # 50..99
        "net_pips": round((digest[1] - digest[2]) * 0.5, 2),
        "win_rate": round(0.40 + (digest[3] / 255) * 0.20, 4),  # 0.40..0.60
        "sharpe": round((digest[4] - 128) / 50.0, 3),            # -2.56..2.54
        "max_dd_pips": round(-(digest[5] / 255) * 30, 1),         # 0..-30
    }

    now_iso = datetime.now(timezone.utc).isoformat()
    scorecard: dict[str, object] = {
        "cell_id": cid,
        "seed": seed,
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "metrics": metrics,
        "started_at": now_iso,
        "finished_at": now_iso,  # v1 stub: instantaneous
        "local_fallback": True,
        "v1_stub": True,
    }

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(scorecard, indent=2, sort_keys=True)
        )
    return scorecard
