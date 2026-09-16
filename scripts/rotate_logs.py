#!/usr/bin/env python3
"""Forward-test log rotation script.

Archives ``logs/*.log`` files older than 7 days into
``logs/archive/<YYYY-MM-DD>/<basename>.log.gz`` and deletes archive
entries older than 90 days. Idempotent: re-running on a clean tree is a
no-op. Supports ``--dry-run`` to print planned actions without touching
the filesystem.

State for downstream audit (e.g. ``scripts/daily_audit.py``) lives in
``logs/archive/.rotation_state.json`` — last run timestamp, archive count,
and any failure markers.

Usage::

    scripts/rotate_logs.py                      # rotate per policy
    scripts/rotate_logs.py --dry-run             # print plan, no writes
    scripts/rotate_logs.py --archive-days 7      # override archive threshold
    scripts/rotate_logs.py --purge-days 90       # override purge threshold
    scripts/rotate_logs.py --logs-root /path     # override log root

Designed for cron; emits one ``STATE`` line per archive/purge action and
exits non-zero on hard failure so the cron runner can surface it.
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOGS_ROOT = ROOT / "logs"
DEFAULT_ARCHIVE_DIR = DEFAULT_LOGS_ROOT / "archive"
STATE_FILENAME = ".rotation_state.json"
EXIT_OK = 0
EXIT_HARD_FAILURE = 2


@dataclass
class RotationPlan:
    """Planned actions for a rotation run."""

    archive: list[Path] = field(default_factory=list)
    purge: list[Path] = field(default_factory=list)
    skipped_recent: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--logs-root",
        type=Path,
        default=DEFAULT_LOGS_ROOT,
        help="Directory containing .log files to rotate (default: %(default)s)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Archive directory (default: <logs-root>/archive)",
    )
    parser.add_argument(
        "--archive-days",
        type=int,
        default=7,
        help="Archive .log files older than N days (default: %(default)s)",
    )
    parser.add_argument(
        "--purge-days",
        type=int,
        default=90,
        help="Delete archived entries older than N days (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without touching the filesystem",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="State file path (default: <archive-dir>/.rotation_state.json)",
    )
    return parser.parse_args(argv)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _file_age_days(path: Path, *, now: datetime) -> int:
    """Return the age of ``path`` in whole days, based on mtime."""
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    delta = now - mtime
    return max(int(delta.total_seconds() // 86400), 0)


def _archive_subdir(archive_dir: Path, *, when: datetime) -> Path:
    sub = archive_dir / when.strftime("%Y-%m-%d")
    sub.mkdir(parents=True, exist_ok=True)
    return sub


def _build_archive_plan(
    logs_root: Path,
    archive_dir: Path,
    archive_days: int,
    *,
    now: datetime,
) -> list[Path]:
    """Return list of .log files in ``logs_root`` older than ``archive_days``."""
    candidates: list[Path] = []
    if not logs_root.exists():
        return candidates
    for entry in sorted(logs_root.iterdir()):
        if not entry.is_file():
            continue
        if entry.suffix != ".log":
            continue
        # Skip the live forward_test.log — that's the actively-written file.
        # Live logs that exceed the threshold stay put until the launcher
        # rotates them; this script is for archived/abandoned logs only.
        if entry.name == "forward_test.log":
            continue
        if _file_age_days(entry, now=now) >= archive_days:
            candidates.append(entry)
    return candidates


def _build_purge_plan(
    archive_dir: Path,
    purge_days: int,
    *,
    now: datetime,
) -> list[Path]:
    """Return list of archive files (recursively) older than ``purge_days``."""
    purged: list[Path] = []
    if not archive_dir.exists():
        return purged
    for entry in sorted(archive_dir.rglob("*.gz")):
        if _file_age_days(entry, now=now) >= purge_days:
            purged.append(entry)
    return purged


def _gzip_to_archive(
    src: Path,
    archive_dir: Path,
    *,
    when: datetime,
    dry_run: bool,
) -> Path:
    """Gzip ``src`` into ``<archive_dir>/<YYYY-MM-DD>/<basename>.log.gz``.

    Returns the destination path. Idempotent: skips if destination exists.
    """
    sub = archive_dir / when.strftime("%Y-%m-%d")
    if not dry_run:
        sub.mkdir(parents=True, exist_ok=True)
    dst = sub / f"{src.name}.gz"
    if dst.exists():
        return dst
    if dry_run:
        return dst
    # Stream the gzip write — large logs shouldn't buffer fully in memory.
    with src.open("rb") as fin, gzip.open(dst, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)
    return dst


def _remove(path: Path, *, dry_run: bool) -> None:
    if dry_run:
        return
    path.unlink()


def _write_state(
    state_file: Path,
    *,
    now: datetime,
    archived: list[Path],
    purged: list[Path],
    dry_run: bool,
) -> dict[str, Any]:
    """Persist last-run state for the audit check."""
    payload: dict[str, Any] = {
        "last_run_at": now.isoformat(),
        "dry_run": dry_run,
        "archived_count": len(archived),
        "purged_count": len(purged),
        "archived_samples": [str(p) for p in archived[:10]],
        "purged_samples": [str(p) for p in purged[:10]],
    }
    if not dry_run:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(state_file.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(state_file)
    return payload


def rotate(
    logs_root: Path,
    archive_dir: Path,
    state_file: Path,
    *,
    archive_days: int = 7,
    purge_days: int = 90,
    dry_run: bool = False,
    now: datetime | None = None,
) -> RotationPlan:
    """Run one rotation cycle. Returns a :class:`RotationPlan` summary."""
    now = now or _now_utc()
    plan = RotationPlan()
    archive_targets = _build_archive_plan(
        logs_root,
        archive_dir,
        archive_days,
        now=now,
    )
    for src in archive_targets:
        try:
            dst = _gzip_to_archive(
                src,
                archive_dir,
                when=now,
                dry_run=dry_run,
            )
            plan.archive.append(dst)
            if not dry_run:
                # logrotate convention: source is removed once its compressed
                # copy lands in the archive. Without this the next run sees
                # the same stale file and re-archives it.
                _remove(src, dry_run=False)
        except OSError as exc:
            plan.errors.append(f"archive failed for {src}: {exc}")

    purge_targets = _build_purge_plan(archive_dir, purge_days, now=now)
    for gz in purge_targets:
        try:
            _remove(gz, dry_run=dry_run)
            plan.purge.append(gz)
        except OSError as exc:
            plan.errors.append(f"purge failed for {gz}: {exc}")

    _write_state(
        state_file,
        now=now,
        archived=plan.archive,
        purged=plan.purge,
        dry_run=dry_run,
    )
    return plan


def _emit_plan(plan: RotationPlan, *, dry_run: bool) -> None:
    prefix = "DRY-RUN" if dry_run else "STATE"
    if plan.archive:
        print(f"[ROTATE] {prefix} archive {len(plan.archive)} file(s):")
        for p in plan.archive:
            print(f"  - {p}")
    if plan.purge:
        print(f"[ROTATE] {prefix} purge {len(plan.purge)} archive(s):")
        for p in plan.purge:
            print(f"  - {p}")
    if not plan.archive and not plan.purge:
        print("[ROTATE] STATE no-op (logs and archive within policy)")
    for err in plan.errors:
        print(f"[ROTATE] ERROR {err}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logs_root: Path = args.logs_root.resolve()
    archive_dir: Path = (args.archive_dir or (logs_root / "archive")).resolve()
    state_file: Path = (args.state_file or (archive_dir / STATE_FILENAME)).resolve()

    if not logs_root.exists():
        print(f"[ROTATE] ERROR logs root does not exist: {logs_root}", file=sys.stderr)
        return EXIT_HARD_FAILURE
    if args.archive_days < 1:
        print("[ROTATE] ERROR --archive-days must be >= 1", file=sys.stderr)
        return EXIT_HARD_FAILURE
    if args.purge_days <= args.archive_days:
        print(
            "[ROTATE] ERROR --purge-days must exceed --archive-days",
            file=sys.stderr,
        )
        return EXIT_HARD_FAILURE

    plan = rotate(
        logs_root,
        archive_dir,
        state_file,
        archive_days=args.archive_days,
        purge_days=args.purge_days,
        dry_run=args.dry_run,
    )
    _emit_plan(plan, dry_run=args.dry_run)
    if plan.errors:
        return EXIT_HARD_FAILURE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
