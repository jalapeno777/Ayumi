"""JSONL appender for ``dispatch_skipped.jsonl`` (Q1 loud-skew rejection log).

Per Tomoe brief (brief §2 + card AC4 extended) + Q3 (db_sha drift):

- Each call to :func:`append_skipped` writes one line to
  ``{output_root}/dispatch_skipped.jsonl``.
- Row schema: ``{cell_id, reason, expected, actual, ts, ...extra}``.
- Known reasons: ``code_skew`` (Q1 loud ABORT), ``db_sha_drift``
  (Q3 resume-detection), ``bundle_too_large`` (Q3.b), future
  ``bundle_validation_failed``, etc.
- flock-protected so concurrent dispatchers can't interleave bytes.
- One log per run-id (not global); keeps the audit clean per run.

The runner is responsible for the ``re-raise`` after calling this
helper — this module only persists the row.
"""

from __future__ import annotations

import fcntl
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["append_skipped"]


def append_skipped(
    output_root: Path,
    *,
    cell_id: str,
    reason: str,
    expected: str | None = None,
    actual: str | None = None,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Append one row to ``{output_root}/dispatch_skipped.jsonl``.

    The lock is on ``dispatch_skipped.lock`` — distinct from the per-cell
    ``manifest.lock`` (Q4.c) so the two contention domains don't fight.

    Args:
        output_root: dispatcher-side run root (manifests/scorecards also
            land under here).
        cell_id: per-cell unique ID (Q4 v1 == seed).
        reason: short snake_case tag (``code_skew`` | ``db_sha_drift`` |
            ``bundle_too_large`` | ...).
        expected: prior-expected value that was violated (e.g. dispatcher's
            bundle_sha for ``code_skew``; current db_sha for ``db_sha_drift``).
        actual: observed value that caused the skip.
        extra: arbitrary auxiliary fields merged into the row. Useful for
            context (e.g. ``{"git_sha": ..., "env_lock_hash": ...}``).

    Note:
        flock-protected; safe for concurrent dispatchers. Creates
        ``output_root`` if missing. Caller must re-raise / decide skip
        vs continue vs abort after this call returns.
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_root / "dispatch_skipped.jsonl"
    lock_path = output_root / "dispatch_skipped.lock"

    row: dict[str, object] = {
        "cell_id": cell_id,
        "reason": reason,
        "expected": expected,
        "actual": actual,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        for k, v in extra.items():
            row.setdefault(k, v)  # don't clobber the canonical keys above
    line = json.dumps(row, sort_keys=True) + "\n"

    with lock_path.open("a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            with jsonl_path.open("a") as jf:
                jf.write(line)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
