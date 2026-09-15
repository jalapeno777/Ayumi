"""Unit tests for ``dispatch_skipped`` (JSONL appender).

Coverage:
- Row schema matches Tomoe brief §2 + card AC4 extended:
  ``{cell_id, reason, expected, actual, ts, ...extras}`` (canonical keys
  cannot be overridden by ``extras``; ``setdefault`` semantics).
- ``flock``-protected append (concurrent threads can't interleave bytes
  in the JSONL output).
- Append mode: each call writes one new line, does not overwrite
  existing content.
- Output root auto-creation if missing.
"""

from __future__ import annotations

import json

from offload.dispatch_skipped import append_skipped


def test_jsonl_row_canonical_keys(tmp_path) -> None:
    """Row schema includes all 5 canonical keys in expected order/positions."""
    jsonl_path = tmp_path / "dispatch_skipped.jsonl"
    out_root = tmp_path
    append_skipped(
        out_root,
        cell_id="abc1234",
        reason="code_skew",
        expected="sha-expected-001",
        actual="sha-actual-002",
    )
    raw = jsonl_path.read_text().strip()
    row = json.loads(raw)
    # All five canonical keys present, in order.
    assert list(row.keys())[:5] == ["actual", "cell_id", "expected", "reason", "ts"]
    assert row["cell_id"] == "abc1234"
    assert row["reason"] == "code_skew"
    assert row["expected"] == "sha-expected-001"
    assert row["actual"] == "sha-actual-002"
    # ts is ISO 8601 UTC (offset present, starts with date-time).
    assert row["ts"][:10].count("-") == 2  # YYYY-MM-DD
    assert "T" in row["ts"]


def test_extras_merge_preserves_canonical_keys(tmp_path) -> None:
    """``extras`` adds new keys but cannot override the 5 canonical ones."""
    append_skipped(
        tmp_path,
        cell_id="canonical-cell-id",
        reason="db_sha_drift",
        expected="sha-canonical-expected",
        actual="sha-canonical-actual",
        extra={
            "cell_id": "OVERRIDE-ATTEMPT",   # must NOT clobber canonical
            "reason": "OVERRIDE-REASON",    # must NOT clobber canonical
            "git_sha": "deadbeef0001",        # new key OK
            "run_id": "test-merge",
        },
    )
    row = json.loads((tmp_path / "dispatch_skipped.jsonl").read_text().strip())
    assert row["cell_id"] == "canonical-cell-id"  # canonical preserved
    assert row["reason"] == "db_sha_drift"        # canonical preserved
    assert row["git_sha"] == "deadbeef0001"      # new key merged
    assert row["run_id"] == "test-merge"          # new key merged


def test_appends_dont_overwrite_existing_content(tmp_path) -> None:
    """Each call appends a new line; prior content is preserved."""
    for i in range(3):
        append_skipped(
            tmp_path,
            cell_id=f"cell-{i}",
            reason="code_skew",
            expected=str(i),
            actual=str(i * 10),
        )
    raw = (tmp_path / "dispatch_skipped.jsonl").read_text()
    lines = raw.strip().splitlines()
    assert len(lines) == 3
    rows = [json.loads(line) for line in lines]
    assert [r["cell_id"] for r in rows] == ["cell-0", "cell-1", "cell-2"]


def test_appends_create_output_root_if_missing(tmp_path) -> None:
    """Missing output_root is created by the helper (mkdir -p semantics)."""
    nested_out = tmp_path / "a" / "b" / "c"  # doesn't exist yet
    assert not nested_out.exists()
    append_skipped(
        nested_out, cell_id="x", reason="code_skew", expected="e", actual="a",
    )
    assert nested_out.is_dir()
    assert (nested_out / "dispatch_skipped.jsonl").is_file()


def test_row_extra_is_optional(tmp_path) -> None:
    """``extras`` keyword can be omitted; row still has 5 canonical keys."""
    append_skipped(
        tmp_path, cell_id="y", reason="bundle_too_large", expected="e", actual="a"
    )
    row = json.loads((tmp_path / "dispatch_skipped.jsonl").read_text().strip())
    assert set(row.keys()) == {"actual", "cell_id", "expected", "reason", "ts"}


def test_flock_serializes_concurrent_appenders(tmp_path) -> None:
    """Two threads appending simultaneously → no byte-level interleaving
    in the resulting JSONL (each line is a complete JSON object)."""
    import threading

    jsonl_path = tmp_path / "dispatch_skipped.jsonl"

    def writer(n: int) -> None:
        for i in range(n):
            append_skipped(
                tmp_path,
                cell_id=f"thr-{n}-{i}",
                reason="code_skew",
                expected=str(n),
                actual=str(i),
            )

    t1 = threading.Thread(target=writer, args=(1,))
    t2 = threading.Thread(target=writer, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive() and not t2.is_alive()

    raw = jsonl_path.read_text()
    lines = raw.splitlines()
    assert len(lines) == 3
    # Each line MUST parse as a complete JSON object (no interleaved bytes).
    for line in lines:
        row = json.loads(line)  # would raise if bytes were sliced mid-line
        assert row["cell_id"].startswith("thr-")
