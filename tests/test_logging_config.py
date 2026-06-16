"""Tests for common.logging_config — structured logging setup.

All tests use tmp_path to avoid writing to the real logs/ directory.
"""

import logging
import re
from pathlib import Path

import pytest

from common.logging_config import (
    DEFAULT_FORMAT,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot and restore root logger handlers around each test."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_setup_creates_log_dir(tmp_path):
    """setup_logging creates the log directory if it doesn't exist."""
    log_dir = tmp_path / "logs"
    assert not log_dir.exists()

    setup_logging(log_dir=str(log_dir), console=False)

    assert log_dir.exists()
    assert log_dir.is_dir()


def test_log_file_receives_messages(tmp_path):
    """Messages logged after setup appear in the log file."""
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=str(log_dir), log_name="test_run", level="INFO", console=False)

    test_msg = "spinach was here"
    logging.info(test_msg)

    # Flush all handlers
    for h in logging.getLogger().handlers:
        h.flush()

    log_file = log_dir / "test_run.log"
    assert log_file.exists(), f"Log file {log_file} not created"

    content = log_file.read_text(encoding="utf-8")
    assert test_msg in content, f"Message '{test_msg}' not found in log content"


def test_rotation_backup_count_set(tmp_path):
    """TimedRotatingFileHandler is configured with the requested backupCount."""
    log_dir = tmp_path / "logs"
    setup_logging(
        log_dir=str(log_dir),
        log_name="rotation_test",
        backup_count=3,
        console=False,
    )

    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    assert len(file_handlers) == 1, "Expected exactly one TimedRotatingFileHandler"
    assert file_handlers[0].backupCount == 3, "backupCount not set correctly"


def test_idempotent(tmp_path):
    """Calling setup_logging twice replaces handlers, doesn't accumulate."""
    log_dir = tmp_path / "logs"

    setup_logging(log_dir=str(log_dir), log_name="first", console=True)
    first_count = len(logging.getLogger().handlers)

    setup_logging(log_dir=str(log_dir), log_name="second", console=True)
    second_count = len(logging.getLogger().handlers)

    assert first_count == second_count, (
        f"Handler count changed: {first_count} → {second_count}"
    )
    # With console=True we expect exactly 2 handlers (file + console)
    assert second_count == 2, f"Expected 2 handlers, got {second_count}"


def test_format_contains_timestamp_and_level(tmp_path):
    """Log output matches DEFAULT_FORMAT with timestamp, level, name, message."""
    log_dir = tmp_path / "logs"
    setup_logging(
        log_dir=str(log_dir),
        log_name="format_test",
        level="WARNING",
        console=False,
    )

    logger_name = "ayumi.test.format"
    logger = logging.getLogger(logger_name)
    logger.warning("format check message")

    for h in logging.getLogger().handlers:
        h.flush()

    log_file = log_dir / "format_test.log"
    content = log_file.read_text(encoding="utf-8")

    # Expected format: "2026-06-16 12:00:00 | WARNING  | ayumi.test.format | format check message"
    pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"  # timestamp
        r" \| WARNING\s+\|"  # level (padded to 8)
        r" " + re.escape(logger_name) + r" \| "  # logger name
        r"format check message"  # message
    )
    lines = [ln for ln in content.strip().splitlines() if "format check message" in ln]
    assert len(lines) == 1, f"Expected 1 matching line, got {len(lines)}"
    assert pattern.search(lines[0]), (
        f"Line '{lines[0]}' does not match format '{DEFAULT_FORMAT}'"
    )
