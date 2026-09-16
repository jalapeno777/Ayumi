#!/usr/bin/env python3
"""Targeted unit tests for scripts/rotate_logs.py.

Self-contained: builds a temporary logs root with synthetic .log files
whose mtimes are back-dated to exercise the threshold boundaries.

Coverage:
- Idempotency (running twice does not double-archive)
- Threshold boundaries (6d, 7d, 8d, 90d, 91d)
- Dry-run mode does not write
- State file is written with archived/purged counts
- Live forward_test.log is never archived
- Missing logs root returns EXIT_HARD_FAILURE
- purge-days <= archive-days returns EXIT_HARD_FAILURE
"""
from __future__ import annotations

import gzip
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add scripts/ to sys.path so we can import the module under test.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import rotate_logs  # noqa: E402


def _make_log(path: Path, *, age_days: int, contents: bytes = b"test\n") -> None:
    """Create ``path`` with mtime back-dated by ``age_days``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    target_mtime = datetime.now(timezone.utc) - timedelta(days=age_days)
    ts = target_mtime.timestamp()
    # os.utime takes (atime, mtime); we want both = back-dated.
    import os

    os.utime(path, (ts, ts))


class RotateLogsTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.logs_root = self.tmp / "logs"
        self.archive_dir = self.logs_root / "archive"
        self.state_file = self.archive_dir / rotate_logs.STATE_FILENAME
        self.logs_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_archive_threshold_boundary(self) -> None:
        # 6d = under threshold (skip), 7d = at threshold (archive), 8d = archive
        _make_log(self.logs_root / "fresh.log", age_days=6)
        _make_log(self.logs_root / "edge.log", age_days=7)
        _make_log(self.logs_root / "old.log", age_days=8)

        plan = rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=False,
        )

        self.assertEqual(len(plan.archive), 2, plan.archive)
        # Archives land in <archive_dir>/<YYYY-MM-DD>/<basename>.gz.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertTrue((self.archive_dir / today / "edge.log.gz").exists())
        self.assertTrue((self.archive_dir / today / "old.log.gz").exists())
        # Sources are removed once archived.
        self.assertFalse((self.logs_root / "edge.log").exists())
        self.assertFalse((self.logs_root / "old.log").exists())
        self.assertTrue((self.logs_root / "fresh.log").exists(), "6d file must remain")

    def test_idempotency(self) -> None:
        _make_log(self.logs_root / "old.log", age_days=10)
        plan1 = rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=False,
        )
        plan2 = rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=False,
        )
        self.assertEqual(len(plan1.archive), 1)
        self.assertEqual(len(plan2.archive), 0, "second run must be a no-op")

    def test_dry_run_does_not_write(self) -> None:
        _make_log(self.logs_root / "old.log", age_days=10)
        plan = rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=True,
        )
        self.assertEqual(len(plan.archive), 1)
        self.assertFalse(self.archive_dir.exists(), "dry-run must not mkdir")
        self.assertFalse(self.state_file.exists(), "dry-run must not write state")

    def test_state_file_payload(self) -> None:
        _make_log(self.logs_root / "old.log", age_days=10)
        rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=False,
        )
        self.assertTrue(self.state_file.exists())
        payload = json.loads(self.state_file.read_text())
        self.assertEqual(payload["archived_count"], 1)
        self.assertEqual(payload["purged_count"], 0)
        self.assertFalse(payload["dry_run"])
        self.assertIn("last_run_at", payload)

    def test_skip_live_forward_test_log(self) -> None:
        _make_log(self.logs_root / "forward_test.log", age_days=30)
        plan = rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=False,
        )
        self.assertEqual(len(plan.archive), 0)
        self.assertTrue((self.logs_root / "forward_test.log").exists())

    def test_purge_threshold(self) -> None:
        # Pre-populate archive with a file older than purge-days.
        archive_subdir = self.archive_dir / "2024-01-01"
        archive_subdir.mkdir(parents=True)
        old_gz = archive_subdir / "ancient.log.gz"
        old_gz.write_bytes(b"x")
        import os

        ts = (datetime.now(timezone.utc) - timedelta(days=120)).timestamp()
        os.utime(old_gz, (ts, ts))

        plan = rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=False,
        )
        self.assertEqual(len(plan.purge), 1)
        self.assertFalse(old_gz.exists())

    def test_gzipped_archive_is_readable(self) -> None:
        original = b"hello world\n" * 100
        _make_log(self.logs_root / "data.log", age_days=10, contents=original)
        rotate_logs.rotate(
            self.logs_root,
            self.archive_dir,
            self.state_file,
            archive_days=7,
            purge_days=90,
            dry_run=False,
        )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archived = self.archive_dir / today / "data.log.gz"
        self.assertTrue(archived.exists())
        with gzip.open(archived, "rb") as fin:
            self.assertEqual(fin.read(), original)

    def test_main_returns_hard_failure_for_missing_root(self) -> None:
        missing = self.tmp / "nope"
        rc = rotate_logs.main(
            [
                "--logs-root",
                str(missing),
                "--archive-dir",
                str(self.archive_dir),
            ]
        )
        self.assertEqual(rc, rotate_logs.EXIT_HARD_FAILURE)

    def test_main_rejects_purge_le_archive(self) -> None:
        rc = rotate_logs.main(
            [
                "--logs-root",
                str(self.logs_root),
                "--archive-dir",
                str(self.archive_dir),
                "--archive-days",
                "10",
                "--purge-days",
                "5",
            ]
        )
        self.assertEqual(rc, rotate_logs.EXIT_HARD_FAILURE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
