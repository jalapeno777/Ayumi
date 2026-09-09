"""Targeted tests for the version-aware snapshot pool resolver in roll_trait.

The resolver (`resolve_snapshot_pool` in scripts/pregnancy/roll_trait.py) must
discover snapshots produced by `scripts/pregnancy/snapshot_pool.py`, which
emits `trait_pool_<name>.snapshot-<date>.json` + `snapshots-manifest.json`
under `--out-dir`. The pre-rework resolver looked for
`$PREGNANCY_POOL_DIR/<pv>/<base_name>` and
`<parent>/pools/<pv>/<base_name>`, which snapshot_pool.py never produces —
so produced snapshots were undiscoverable.

These tests cover:
- Manifest-based lookup (the primary lookup path)
- Version normalization between record pool_version (`v1.0`) and manifest
  pool_version (`v1`)
- SHA-256 verification on manifest entries
- Dated-filename glob fallback when no manifest is present
- Missing-snapshot behavior returns None (warning + verify-pass preserved)
- End-to-end: an actual snapshot_pool.py emission is discovered by the
  resolver used inside `verify_ledger` with the v1.0 → v1 normalization.

Per HR5, only this targeted test file is run; never the full pytest suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Allow importing scripts/pregnancy/roll_trait.py by path even when pytest is
# invoked from the repo root.
sys.path.insert(0, str(ROOT / "scripts" / "pregnancy"))

import roll_trait  # noqa: E402

SNAPSHOT_PY = ROOT / "scripts" / "pregnancy" / "snapshot_pool.py"


def _write_pool(path: Path, *, pool_name: str, version: int, categories: list[str]) -> dict:
    """Write a minimal valid trait pool. Returns the parsed dict."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pool: dict = {
        "_meta": {
            "pool_name": pool_name,
            "version": version,
            "spec": f"test fixture pool {pool_name} v{version}",
            "categories": categories,
            "created_at": "2026-09-09T00:00:00Z",
        },
    }
    for cat in categories:
        pool[cat] = [
            {"id": f"{cat}_a", "label": f"{cat} A", "origin": "ava"},
            {"id": f"{cat}_b", "label": f"{cat} B", "origin": "craig"},
        ]
    path.write_text(json.dumps(pool, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return pool


def test_normalize_pool_version():
    assert roll_trait._normalize_pool_version("v1") == "v1"
    assert roll_trait._normalize_pool_version("v1.0") == "v1"
    assert roll_trait._normalize_pool_version("v1.0.0") == "v1"
    assert roll_trait._normalize_pool_version("v2.3.0") == "v2.3"
    assert roll_trait._normalize_pool_version("") == ""
    assert roll_trait._normalize_pool_version("v1.2.3") == "v1.2.3"


def test_resolve_from_manifest_exact_match(tmp_path):
    """snapshot_pool.py produces a manifest with pool_version="v1"; the
    resolver must discover it when asked for either "v1" or the legacy "v1.0"."""
    pool_path = tmp_path / "trait_pool_harem_v1.json"
    _write_pool(pool_path, pool_name="harem_v1", version=1, categories=["voice_tone"])
    rc = subprocess.run(  # noqa: S603
        [sys.executable, str(SNAPSHOT_PY), "--pool", str(pool_path),
         "--date", "2026-09-09"],
        capture_output=True, text=True, check=True,
    )
    assert "snapshot OK" in rc.stdout, rc.stderr
    assert (tmp_path / "snapshots-manifest.json").exists()
    assert (tmp_path / "trait_pool_harem_v1.snapshot-2026-09-09.json").exists()

    # Exact match: ask for "v1"
    snap = roll_trait.resolve_snapshot_pool("v1", pool_path)
    assert snap is not None, "manifest lookup failed for exact match 'v1'"
    assert snap["_meta"]["pool_name"] == "harem_v1"
    assert snap["_meta"]["version"] == 1
    assert "voice_tone" in snap

    # Normalized match: ask for "v1.0" (the legacy pool_version_from_pool form)
    snap2 = roll_trait.resolve_snapshot_pool("v1.0", pool_path)
    assert snap2 is not None, "manifest lookup failed for normalized 'v1.0'"
    assert snap2["_meta"]["version"] == 1

    # Wrong version → None
    snap3 = roll_trait.resolve_snapshot_pool("v2", pool_path)
    assert snap3 is None


def test_resolve_from_manifest_sha256_mismatch_returns_none(tmp_path):
    """If the manifest's recorded sha256 doesn't match the file bytes, the
    resolver must refuse that entry and fall back. With only one entry and
    no glob fallback available, it returns None."""
    pool_path = tmp_path / "trait_pool_harem_v1.json"
    _write_pool(pool_path, pool_name="harem_v1", version=1, categories=["voice_tone"])
    subprocess.run(  # noqa: S603
        [sys.executable, str(SNAPSHOT_PY), "--pool", str(pool_path),
         "--date", "2026-09-09"],
        capture_output=True, text=True, check=True,
    )
    # Tamper with the snapshot bytes WITHOUT updating the manifest's sha256.
    snap_file = tmp_path / "trait_pool_harem_v1.snapshot-2026-09-09.json"
    snap_file.write_text(
        snap_file.read_text(encoding="utf-8").replace("voice_tone A", "voice_tone TAMPERED"),
        encoding="utf-8",
    )
    # Move the manifest away so the dated-glob fallback cannot rescue us.
    # This forces the resolver to rely on the tampered manifest entry only.
    (tmp_path / "snapshots-manifest.json").rename(tmp_path / "manifest.bak.json")
    # Also delete the snapshot's dated file so the glob fallback can't find it.
    snap_file.unlink()
    snap = roll_trait.resolve_snapshot_pool("v1", pool_path)
    assert snap is None, "sha256 mismatch must yield None (refuse tampered snapshot)"


def test_resolve_from_dated_glob_without_manifest(tmp_path):
    """If the manifest is absent but a snapshot file matching the dated
    pattern is present, the glob fallback must still discover it."""
    pool_path = tmp_path / "trait_pool_harem_v1.json"
    _write_pool(pool_path, pool_name="harem_v1", version=1, categories=["voice_tone"])
    # Generate via snapshot_pool.py then remove the manifest.
    subprocess.run(  # noqa: S603
        [sys.executable, str(SNAPSHOT_PY), "--pool", str(pool_path),
         "--date", "2026-09-09"],
        capture_output=True, text=True, check=True,
    )
    (tmp_path / "snapshots-manifest.json").unlink()

    snap = roll_trait.resolve_snapshot_pool("v1", pool_path)
    assert snap is not None, "dated-glob fallback failed"
    assert snap["_meta"]["pool_name"] == "harem_v1"

    # Normalized query also works against the glob fallback.
    snap2 = roll_trait.resolve_snapshot_pool("v1.0", pool_path)
    assert snap2 is not None
    assert snap2["_meta"]["version"] == 1


def test_resolve_missing_snapshot_returns_none(tmp_path, monkeypatch):
    """When no snapshot exists for `pool_version`, the resolver returns None.
    Missing-snapshot is a warning, not a failure — see verify_ledger test."""
    pool_path = tmp_path / "trait_pool_harem_v1.json"
    _write_pool(pool_path, pool_name="harem_v1", version=1, categories=["voice_tone"])
    monkeypatch.delenv("PREGNANCY_POOL_DIR", raising=False)
    assert roll_trait.resolve_snapshot_pool("v99", pool_path) is None
    assert roll_trait.resolve_snapshot_pool("", pool_path) is None
    assert roll_trait.resolve_snapshot_pool("(absent)", pool_path) is None


def test_resolve_via_pregnancy_pool_dir_env(tmp_path, monkeypatch):
    """The resolver honors $PREGNANCY_POOL_DIR as the first candidate dir,
    even when no snapshots live next to the live pool."""
    snap_dir = tmp_path / "external_snapshots"
    snap_dir.mkdir()
    live_pool = tmp_path / "live" / "trait_pool_harem_v1.json"
    live_pool.parent.mkdir(parents=True, exist_ok=True)
    _write_pool(live_pool, pool_name="harem_v1", version=1, categories=["voice_tone"])
    subprocess.run(  # noqa: S603
        [sys.executable, str(SNAPSHOT_PY), "--pool", str(live_pool),
         "--out-dir", str(snap_dir), "--date", "2026-09-09"],
        capture_output=True, text=True, check=True,
    )
    monkeypatch.setenv("PREGNANCY_POOL_DIR", str(snap_dir))
    snap = roll_trait.resolve_snapshot_pool("v1", live_pool)
    assert snap is not None
    assert snap["_meta"]["pool_name"] == "harem_v1"


def test_resolve_picks_latest_snapshot_among_many(tmp_path):
    """When the manifest holds multiple snapshots for the same pool_version,
    the resolver must pick the latest by date (lex-descending YYYY-MM-DD)."""
    pool_path = tmp_path / "trait_pool_harem_v1.json"
    _write_pool(pool_path, pool_name="harem_v1", version=1, categories=["voice_tone"])
    for date in ("2026-08-01", "2026-09-09", "2026-08-15"):
        subprocess.run(  # noqa: S603
            [sys.executable, str(SNAPSHOT_PY), "--pool", str(pool_path),
             "--date", date],
            capture_output=True, text=True, check=True,
        )
    snap = roll_trait.resolve_snapshot_pool("v1", pool_path)
    assert snap is not None
    # The latest snapshot by date is 2026-09-09.
    manifest = json.loads((tmp_path / "snapshots-manifest.json").read_text(encoding="utf-8"))
    chosen_date = max(e["date"] for e in manifest["snapshots"])
    assert snap["_meta"]["version"] == 1
    # Confirm the resolved file matches the chosen manifest entry by sha256.
    expected = next(
        e for e in manifest["snapshots"]
        if e["date"] == chosen_date and e["pool_version"] == "v1"
    )
    import hashlib
    raw = (tmp_path / expected["snapshot_file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected["sha256"]


def test_end_to_end_resolver_inside_verify_ledger(tmp_path):
    """End-to-end: a snapshot produced by snapshot_pool.py is consumed by
    resolve_snapshot_pool() via the verify_ledger path. The live pool is at
    v2, and the ledger contains a legacy v1 record whose label needs to be
    resolved through the v1 snapshot."""
    # Source v1 pool (used to produce the snapshot).
    src_v1 = tmp_path / "source_v1" / "trait_pool_harem_v1.json"
    _write_pool(src_v1, pool_name="harem_v1", version=1, categories=["voice_tone"])
    # Live v2 pool: same parent as the snapshot output so candidate_dirs[1] hits.
    live_v2_path = tmp_path / "trait_pool_harem_v2.json"
    _write_pool(live_v2_path, pool_name="harem_v2", version=2, categories=["voice_tone"])
    # Generate the v1 snapshot into the live pool's parent directory.
    subprocess.run(  # noqa: S603
        [sys.executable, str(SNAPSHOT_PY), "--pool", str(src_v1),
         "--out-dir", str(tmp_path), "--date", "2026-09-09"],
        capture_output=True, text=True, check=True,
    )
    assert (tmp_path / "snapshots-manifest.json").exists()
    assert (tmp_path / "trait_pool_harem_v1.snapshot-2026-09-09.json").exists()

    # Build a record by hand that carries pool_version="v1.0" (legacy form),
    # referring to v1's "voice_tone_a" entry — which exists only in the
    # snapshot, not in the live v2 pool.
    record: dict = {
        "index": 0,
        "prev_hash": roll_trait.GENESIS_HASH,
        "seed": 42,
        "category": "voice_tone",
        "outcome": {"id": "voice_tone_a", "label": "OLD LABEL", "origin": "ava"},
        "origin": "ava",
        "pool_version": "v1.0",
        "ts": "2026-09-09T00:00:00Z",
    }
    record["hash"] = roll_trait.record_self_hash(record)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    # Run verify_ledger against the live v2 pool — the v1.0 record needs
    # the v1 snapshot to render its label.
    pool = json.loads(live_v2_path.read_text(encoding="utf-8"))
    ok, msg = roll_trait.verify_ledger(ledger, pool=pool, pool_path=live_v2_path)
    assert ok, msg
    # The label rendered in the per-record summary must come from the
    # snapshot (manifest entry's pool) — which has "voice_tone A" (not "OLD LABEL").
    assert "voice_tone A" in msg, f"expected snapshot label in summary; got:\n{msg}"
    assert "unresolved-label" not in msg


def test_end_to_end_verify_passes_when_snapshot_missing(tmp_path):
    """When no snapshot is discoverable, verify_ledger must still pass and
    emit an explicit warning + render <unresolved-label:v?> placeholder.
    Hash integrity is unaffected."""
    pool_path = tmp_path / "trait_pool_harem_v1.json"
    _write_pool(pool_path, pool_name="harem_v1", version=1, categories=["voice_tone"])

    record: dict = {
        "index": 0,
        "prev_hash": roll_trait.GENESIS_HASH,
        "seed": 7,
        "category": "voice_tone",
        "outcome": {"id": "voice_tone_a", "label": "OLD LABEL", "origin": "ava"},
        "origin": "ava",
        "pool_version": "v2.0",
        "ts": "2026-09-09T00:00:00Z",
    }
    record["hash"] = roll_trait.record_self_hash(record)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    ok, msg = roll_trait.verify_ledger(ledger, pool=pool, pool_path=pool_path)
    assert ok, f"missing-snapshot must not fail verify, got:\n{msg}"
    assert "warning:" in msg and "snapshot pool for pool_version=v2.0 not found" in msg
    assert "<unresolved-label:v2.0>" in msg
