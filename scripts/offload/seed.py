"""Deterministic seed + cell_id + env-lock hash derivation.

Q4 flag (Tomoe, 2026-09-15, relayed via Ava): **cell_id == seed** is a
deliberate v1 constraint — both derive from
``sha256(strategy || symbol || timeframe)[:16]``. Single source of truth,
no off-by-one between cell ID (manifest + output_path stem) and the
runtime seed passed to stochastic strategies. Documented in
``scripts/offload/README.md`` so future v2 work does not accidentally split
them.

Q3 (a) flag: ``env_lock_hash`` = SHA256 of ``requirements.txt`` +
``requirements-duckdb.txt`` bytes concatenated. ``env_lock_files`` NAMES
are returned alongside the hash so the manifest can pin them and drift
debugging has the visible filenames.

PEP 604 union syntax (``X | None``); no ``Optional``/``typing.List``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# Q3 (a): lock files whose concatenated bytes seed env_lock_hash.
# Listed in TOMOSTABLE order — order matters for deterministic hash.
ENV_LOCK_FILES: tuple[str, ...] = (
    "requirements.txt",
    "requirements-duckdb.txt",
)


def cell_id(strategy: str, symbol: str, timeframe: str) -> str:
    """Per-cell unique ID. Deliberately same value as :func:`seed` (Q4 v1)."""
    return seed(strategy, symbol, timeframe)


def seed(strategy: str, symbol: str, timeframe: str) -> str:
    """Deterministic seed for stochastic strategies AND cell-uniqueness ID.

    Returns the first 16 hex chars of ``sha256(strategy|symbol|timeframe)``.
    The 16-char (64-bit) space is collision-resistant at our matrix scale
    (68 cells per sprint, well under birthday-bound at 2^32).
    """
    payload = f"{strategy}|{symbol}|{timeframe}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def lock_files_hash(
    repo_root: Path,
    files: tuple[str, ...] = ENV_LOCK_FILES,
) -> tuple[str, list[str]]:
    """SHA256 of concatenated env-lock file bytes; returns ``(hash, seen_names)``.

    Q3 flag: names are returned alongside the hash so the manifest can store
    them (``env_lock_files``). Missing files are silently skipped and their
    name is omitted from ``seen_names``; the hash covers only files that
    existed at capture time. Hash in binary mode so EOL/whitespace
    differences don't matter.
    """
    h = hashlib.sha256()
    seen: list[str] = []
    for rel in files:
        p = Path(repo_root) / rel
        if p.is_file():
            h.update(p.read_bytes())
            seen.append(rel)
    return h.hexdigest(), seen
