#!/usr/bin/env python3
"""Freeze a trait pool to an immutable snapshot + manifest.

Per Pregnancy Protocol v0.5 / A7: structural pool upgrades require a frozen
snapshot before the upgrade lands. v1 must be frozen when v2 first lands.

CLI:
    python3 scripts/pregnancy/snapshot_pool.py --pool <path> [--out-dir <dir>] [--date YYYY-MM-DD]

Outputs (under --out-dir, default = pool's parent directory):
  - <pool_name>.snapshot-<date>.json   — verbatim copy of the pool bytes
  - snapshots-manifest.json            — registry of frozen snapshots

Read-only against the live pool: this script never writes to --pool.
Idempotent: re-running with the same (pool_version, date) is a no-op (exit 0).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_POOL_MISSING = 2
EXIT_POOL_INVALID = 3
EXIT_MANIFEST_INVALID = 4
MANIFEST_FILENAME = "snapshots-manifest.json"
MANIFEST_SCHEMA_VERSION = 1


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pool_bytes(pool_path: Path) -> bytes:
    """Read pool bytes verbatim. Caller never passes these back to the pool path."""
    if not pool_path.exists():
        print(f"error: pool not found: {pool_path}", file=sys.stderr)
        sys.exit(EXIT_POOL_MISSING)
    return pool_path.read_bytes()


def validate_pool(raw: bytes) -> dict[str, Any]:
    """Parse pool JSON and require _meta. Return parsed dict (not the bytes)."""
    try:
        pool = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"error: pool is not valid UTF-8 JSON: {exc}", file=sys.stderr)
        sys.exit(EXIT_POOL_INVALID)
    if not isinstance(pool, dict) or "_meta" not in pool:
        print("error: pool missing _meta block (not a trait pool?)", file=sys.stderr)
        sys.exit(EXIT_POOL_INVALID)
    return pool


def derive_metadata(pool: dict[str, Any]) -> tuple[str, int, str]:
    """Return (pool_version_str, entry_count, pool_name) from a parsed pool."""
    meta = pool["_meta"]
    version_raw = meta.get("version")
    if version_raw is None:
        print("error: pool _meta.version missing", file=sys.stderr)
        sys.exit(EXIT_POOL_INVALID)
    # Accept int or numeric-string. Render as "v<int>".
    try:
        version_int = int(version_raw)
    except (TypeError, ValueError):
        print(f"error: pool _meta.version not an integer: {version_raw!r}", file=sys.stderr)
        sys.exit(EXIT_POOL_INVALID)
    pool_version_str = f"v{version_int}"

    pool_name = meta.get("pool_name") or f"pool_{version_int}"
    if not isinstance(pool_name, str) or not pool_name:
        print("error: pool _meta.pool_name missing or empty", file=sys.stderr)
        sys.exit(EXIT_POOL_INVALID)

    categories = meta.get("categories")
    if not isinstance(categories, list) or not categories:
        print("error: pool _meta.categories missing or empty", file=sys.stderr)
        sys.exit(EXIT_POOL_INVALID)

    entry_count = 0
    for cat in categories:
        options = pool.get(cat)
        if not isinstance(options, list):
            print(f"error: pool category '{cat}' is not a list", file=sys.stderr)
            sys.exit(EXIT_POOL_INVALID)
        entry_count += len(options)

    return pool_version_str, entry_count, pool_name


def snapshot_basename(pool_name: str, date_str: str) -> str:
    return f"trait_pool_{pool_name}.snapshot-{date_str}.json"


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load manifest, returning a fresh structure if absent."""
    if not manifest_path.exists():
        return {"schema_version": MANIFEST_SCHEMA_VERSION, "snapshots": []}
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: manifest unreadable ({exc}): {manifest_path}", file=sys.stderr)
        sys.exit(EXIT_MANIFEST_INVALID)
    if not isinstance(data, dict) or "snapshots" not in data or not isinstance(data["snapshots"], list):
        print(f"error: manifest shape invalid: {manifest_path}", file=sys.stderr)
        sys.exit(EXIT_MANIFEST_INVALID)
    schema_version = data.get("schema_version", MANIFEST_SCHEMA_VERSION)
    if schema_version != MANIFEST_SCHEMA_VERSION:
        print(
            f"error: manifest schema_version {schema_version} != {MANIFEST_SCHEMA_VERSION}",
            file=sys.stderr,
        )
        sys.exit(EXIT_MANIFEST_INVALID)
    return data


def write_manifest(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Atomic manifest write: .tmp then os.replace."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    payload = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, manifest_path)


def write_snapshot(snapshot_path: Path, pool_bytes: bytes) -> None:
    """Atomic snapshot write: .tmp then os.replace. Bytes are copied verbatim."""
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = snapshot_path.with_suffix(snapshot_path.suffix + ".tmp")
    tmp_path.write_bytes(pool_bytes)
    os.replace(tmp_path, snapshot_path)


def find_existing(manifest: dict[str, Any], pool_version: str, date_str: str) -> dict[str, Any] | None:
    for entry in manifest["snapshots"]:
        if entry.get("pool_version") == pool_version and entry.get("date") == date_str:
            return entry
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Freeze a trait pool to an immutable snapshot + manifest")
    p.add_argument("--pool", required=True, type=Path, help="path to the live trait pool JSON (read-only)")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="directory for snapshot + manifest (default: pool's parent directory)")
    p.add_argument("--date", default=None,
                   help="snapshot date YYYY-MM-DD (default: UTC today)")
    return p


def today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def cmd_snapshot(args: argparse.Namespace) -> int:
    pool_path: Path = args.pool.resolve()
    pool_bytes = load_pool_bytes(pool_path)
    pool = validate_pool(pool_bytes)
    pool_version, entry_count, pool_name = derive_metadata(pool)
    pool_sha256 = sha256_hex(pool_bytes)

    date_str = args.date or today_utc()

    out_dir: Path = (args.out_dir.resolve() if args.out_dir else pool_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshot_basename_str = snapshot_basename(pool_name, date_str)
    snapshot_path = out_dir / snapshot_basename_str
    manifest_path = out_dir / MANIFEST_FILENAME

    manifest = load_manifest(manifest_path)
    existing = find_existing(manifest, pool_version, date_str)
    if existing is not None:
        print(
            f"no-op: snapshot already present for {pool_version} @ {date_str} "
            f"(sha256={existing.get('sha256')[:12]}..., file={existing.get('snapshot_file')})"
        )
        return EXIT_OK

    write_snapshot(snapshot_path, pool_bytes)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    new_entry = {
        "pool_name": pool_name,
        "pool_version": pool_version,
        "date": date_str,
        "sha256": pool_sha256,
        "entry_count": entry_count,
        "snapshot_file": snapshot_basename_str,
        "pool_source": str(pool_path),
        "created_at": created_at,
    }
    manifest["snapshots"].append(new_entry)
    write_manifest(manifest_path, manifest)

    print(
        f"snapshot OK: {pool_version} @ {date_str} "
        f"entries={entry_count} sha256={pool_sha256[:12]}... "
        f"file={snapshot_path} manifest={manifest_path}"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return cmd_snapshot(args)


if __name__ == "__main__":
    sys.exit(main())
