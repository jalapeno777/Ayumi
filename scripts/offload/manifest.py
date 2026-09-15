"""Per-cell manifest dataclass + atomic two-phase write + per-cell flock.

Q4.b (Tomoe, brief §4b): **two-phase atomic write** — start with
``manifest.draft.json`` (only ``started_at`` + placeholders); on terminal
completion, ``os.replace(draft, final)`` is POSIX-atomic. ``--resume``
ignores ``*.draft.json``. A leftover ``.draft`` is an in-flight cell,
safely re-runnable. If atomicity isn't guaranteed, partial manifests
poison resume — and poison silently.

Q4.c (Tomoe, brief §4c): **per-cell** ``flock(2)`` on ``manifest.lock``
prevents the ``--resume`` race where two parallel runners would
double-dispatch a cell. Second caller: ``skip-with-warning`` (fails loud,
not wait-and-recheck) per Tomoe rec. ``LOCK_NB`` raises immediately.

Q3 flag: ``env_lock_files`` names are embedded alongside ``env_lock_hash``
for drift debugging (not just the hash). Q7: ``local_fallback`` boolean is
observability — NOT control flow. Q4.e: ``git_sha`` and ``env_lock_hash``
are independent, both checked at cell start.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class Manifest:
    """Per-cell manifest — fields per Tomoe brief §4 + card AC4 (extended)."""

    # Identity (Q4 v1: cell_id == seed)
    cell_id: str
    seed: str
    strategy: str
    symbol: str
    timeframe: str

    # Versions (Q4.e: independent two-SHA split)
    git_sha: str
    env_lock_hash: str
    env_lock_files: list[str] = field(default_factory=list)  # Q3 flag
    db_sha: str | None = None

    # Execution
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str | None = None
    exit_code: int | None = None
    output_path: str | None = None
    output_hash: str | None = None

    # Observability (Q7: NEVER control flow downstream)
    local_fallback: bool = False
    dispatch_skipped: bool = False
    dispatch_skipped_reason: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Manifest":
        return cls(**d)


def atomic_write_manifest(
    manifest: Manifest,
    output_root: Path,
) -> Path:
    """Two-phase atomic write — ``*.draft.json`` → ``manifest.json``.

    Caller MUST hold :func:`per_cell_lock` (Q4.c) to prevent racing writers.
    Returns the final manifest path.
    """
    final = output_root / "manifest.json"
    draft = output_root / "manifest.draft.json"
    final.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text(manifest.to_json())
    os.replace(draft, final)  # POSIX-atomic on same FS (Tomoe Q4.b)
    return final


@contextlib.contextmanager
def per_cell_lock(output_root: Path) -> Iterator[int]:
    """``flock(2)`` on ``manifest.lock`` — prevents parallel ``--resume`` race.

    Q4.c: second caller raises ``RuntimeError`` so the runner
    skip-with-warnings (fails loud per Tomoe rec). ``LOCK_NB`` makes the
    contention immediate, not blocking — caller decides the failure UX.

    Yields:
        The open file descriptor (kept alive to retain the lock).
    """
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / "manifest.lock"
    fd = lock_path.open("w")
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"Another runner holds the lock for {output_root}; "
                f"skip-with-warning per Q4.c"
            ) from exc
        yield fd.fileno()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
