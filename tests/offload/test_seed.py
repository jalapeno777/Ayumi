"""Unit tests for the ``seed`` module.

Coverage:
- Q4 v1 binding: ``cell_id() == seed()`` is a deliberate v1 constraint;
  both derive from the same SHA256 (single source of truth).
- Determinism + length: same inputs → same 16-char hex.
- Q3 (a): ``lock_files_hash`` is SHA256 of concatenated
  ``requirements.txt`` + ``requirements-duckdb.txt`` bytes; names captured.
- Missing-file semantics: ``lock_files_hash`` skips missing files.
- Drift detection: changing a lockfile's bytes changes the hash.
"""

from __future__ import annotations

import pathlib

from offload.seed import ENV_LOCK_FILES, cell_id, lock_files_hash, seed


def test_cell_id_seed_binding_q4_v1() -> None:
    """Q4 v1 binding: ``cell_id()`` and ``seed()`` return identical values."""
    args = ("q1_mw_formation", "GBPUSD", "M5")
    assert cell_id(*args) == seed(*args)


def test_cell_id_is_deterministic_16_chars_hex() -> None:
    cid1 = cell_id("q1_mw_formation", "GBPUSD", "M5")
    cid2 = cell_id("q1_mw_formation", "GBPUSD", "M5")
    assert cid1 == cid2
    assert len(cid1) == 16
    int(cid1, 16)  # raises if not hex


def test_cell_id_distinguishes_triples() -> None:
    """Different (strategy, symbol, tf) → different cell_ids (collision-resistant)."""
    a = cell_id("q1_mw_formation", "GBPUSD", "M5")
    b = cell_id("q1_mw_formation", "GBPUSD", "M15")
    c = cell_id("strategy_v2", "GBPUSD", "M5")
    assert len({a, b, c}) == 3


def test_env_lock_files_constant_q3a() -> None:
    """Q3 (a): both lockfile paths pinned in order — order matters for hash determinism."""
    assert ENV_LOCK_FILES == ("requirements.txt", "requirements-duckdb.txt")


def test_lock_files_hash_against_fake_repo(tmp_path: pathlib.Path) -> None:
    """Q3: hash from concatenated bytes, deterministic, names captured alongside."""
    (tmp_path / "requirements.txt").write_bytes(b"ayumi deps\n")
    (tmp_path / "requirements-duckdb.txt").write_bytes(b"duckdb extra\n")

    h1, names1 = lock_files_hash(tmp_path)
    h2, names2 = lock_files_hash(tmp_path)

    assert h1 == h2  # deterministic
    assert len(h1) == 64  # full SHA256 hex
    assert names1 == list(ENV_LOCK_FILES)


def test_lock_files_hash_skips_missing_files(tmp_path: pathlib.Path) -> None:
    """Missing files are silently skipped; only seen_files end up in names."""
    (tmp_path / "requirements.txt").write_bytes(b"only.txt\n")
    # requirements-duckdb.txt deliberately missing.
    h, names = lock_files_hash(tmp_path)
    assert len(h) == 64
    assert names == ["requirements.txt"]


def test_lock_files_hash_differs_on_content_change(tmp_path: pathlib.Path) -> None:
    """Q3 drift detection: changing a lockfile's bytes changes the hash."""
    (tmp_path / "requirements.txt").write_bytes(b"v1\n")
    (tmp_path / "requirements-duckdb.txt").write_bytes(b"duckdb\n")
    h1, _ = lock_files_hash(tmp_path)
    (tmp_path / "requirements.txt").write_bytes(b"v2-with-extra-line\n")
    h2, _ = lock_files_hash(tmp_path)
    assert h1 != h2
