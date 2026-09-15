"""Fault-injection (chaos) tests for the offload runner.

Validates scenarios 1-4 from card
``27dea9ee-90dc-4e01-a3b8-2531a0688771``:

1. **Kill worker mid-job** — push_bundle succeeds, fetch_output fails
   (simulating the worker being killed before producing output). On
   ``--resume`` only the killed cell is re-executed; completed cells
   stay byte-identical.
2. **Network/transport interruption mid-dispatch** — push_bundle raises
   ``WorktreeUnreachableError``. Runner falls back to local execution
   with ``local_fallback=true``; ``dispatch_skipped.jsonl`` is NOT
   written (fallback is graceful, not loud ABORT).
3. **Version-skew rejection** — worker ``WorkerCell.sha256`` differs
   from the dispatcher's ``bundle_sha``. ``CodeSHARejectedError`` is
   raised (no fallback); a ``code_skew`` audit row is written BEFORE
   the raise; no manifest is created.
4. **Poisoned-output detection** — the manifest's ``output_hash`` is
   tampered after a successful dispatch. ``--resume`` detects the
   mismatch via SHA recomputation, writes an ``output_hash_mismatch``
   audit row, and re-executes the cell.

Scope per dispatch (Ava, 2026-09-15): scenarios 1+3 are the pre-matrix
gate (Sora's "untested fault tolerance is no fault tolerance"
directive). Scenarios 2+4 are added coverage where they fit cleanly.

These tests complement the ``f9414fe1`` regression tests
(``tests/offload/test_run_matrix_remote.py``). Where the prior tests
check the *exception* behavior, this file checks the *audit evidence*
(``dispatch_skipped.jsonl`` rows) and the multi-cell interaction
(skip + re-run on resume with byte-identity invariant on completed
cells).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest
from offload.run_matrix_remote import (
    SMOKE_MATRIX,
    _run_one_cell,
)
from offload.seed import cell_id as _derive_cell_id
from offload.transport import (
    BundleTransport,
    BundleTransportError,
    CodeSHARejectedError,
    WorkerCell,
    WorktreeUnreachableError,
)

# ---------------------------------------------------------------------------
# _ChaosTransport — push_bundle + fetch_output call counters, fault flags.
#
# Mirrors the existing _FakeTransport in test_run_matrix_remote.py with
# additions for the chaos suite:
#   - fetch_calls: list[str] — proves skip-on-resume skipped fetch_output
#   - raise_on_fetch: optional exception (kill-mid-job fault)
# ---------------------------------------------------------------------------


class _ChaosTransport(BundleTransport):
    """Configurable transport for the four chaos scenarios.

    Each instance tracks every ``push_bundle`` and ``fetch_output`` call
    so the skip-vs-rerun invariant can be asserted at the wire boundary
    (not just inferred from the manifest).
    """

    def __init__(
        self,
        *,
        cell_to_return: WorkerCell | None = None,
        fetch_bytes: bytes | None = None,
        raise_on_push: Exception | None = None,
    ) -> None:
        self._cell_to_return = cell_to_return or WorkerCell(
            path="/tmp/ayumi-offload/chaos/bundle",  # noqa: S108 — descriptive fixture path; not used for FS ops
            sha256="deadbeef",
        )
        self._fetch_bytes = fetch_bytes
        self._raise_on_push = raise_on_push
        self.push_calls: list[str] = []
        self.fetch_calls: list[str] = []

    def push_bundle(
        self, run_id: str, bundle_path, expected_sha256: str
    ) -> WorkerCell:
        self.push_calls.append(expected_sha256)
        if self._raise_on_push is not None:
            raise self._raise_on_push
        return self._cell_to_return

    def fetch_output(self, run_id: str, cell_id: str) -> bytes | None:
        self.fetch_calls.append(cell_id)
        return self._fetch_bytes


def _args(*, run_id: str, resume: bool) -> argparse.Namespace:
    """Standard argparse.Namespace for direct _run_one_cell calls."""
    return argparse.Namespace(
        simulate_transport=False, run_id=run_id, resume=resume,
    )


def _common_kwargs(
    *, git_sha: str = "e97cd420e0b6225d42728bc91af9dcca86c7f21e",
) -> dict:
    """Standard kwargs bundle for _run_one_cell in these tests."""
    return dict(
        git_sha=git_sha,
        env_lock_hash_val="9123e0ab" * 8,
        env_lock_files_names=["requirements.txt", "requirements-duckdb.txt"],
        bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive fixture path; not used for FS ops
        bundle_sha="deadbeef",
        bundle_files=[],
    )


def _read_skipped_rows(output_root: Path) -> list[dict]:
    """Read all rows from dispatch_skipped.jsonl as parsed dicts."""
    jsonl_path = output_root / "dispatch_skipped.jsonl"
    if not jsonl_path.is_file():
        return []
    return [
        json.loads(line) for line in jsonl_path.read_text().splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Scenario 1 — Kill worker mid-job → --resume re-runs only the killed cell;
# completed cells stay byte-identical.
# ---------------------------------------------------------------------------


def test_scenario1_kill_midjob_resume_only_reruns_killed_cell(
    tmp_path: Path,
) -> None:
    """Pre-matrix gate scenario 1.

    Two-cell smoke matrix. Cell A (M5) is dispatched cleanly. Cell B
    (M15) is "killed mid-job": push_bundle returns success (cell was
    started) but fetch_output raises ``WorktreeUnreachableError`` (worker
    killed before producing output). Runner writes an ``output_missing``
    audit row and ABORTs — no manifest for cell B.

    On ``--resume`` with a fresh transport per cell:
    - Cell A: ``skipped_resume``; the fresh transport's push_bundle and
      fetch_output are NEVER called; the on-disk output bytes are
      byte-identical to the initial dispatch.
    - Cell B: ``dispatched``; the fresh transport's push_bundle and
      fetch_output are called; the new manifest carries the fresh
      bytes.
    """
    output_root = tmp_path / "chaos-s1"
    run_id = "chaos-s1"

    s, sy, tf_a = SMOKE_MATRIX[0]    # ("q1_mw_formation", "GBPUSD", "M5")
    _s, _sy, tf_b = SMOKE_MATRIX[1]  # ("q1_mw_formation", "GBPUSD", "M15")
    cid_a = _derive_cell_id(s, sy, tf_a)
    cid_b = _derive_cell_id(s, sy, tf_b)

    # Phase 1: dispatch cell A (healthy), cell B (kill mid-job).
    # The "kill mid-job" fault: push_bundle returns success (cell was
    # started on the worker) but fetch_output returns None (worker was
    # killed before producing output). The runner's output_missing
    # branch writes the audit row + ABORTs — no manifest for cell B.
    # This matches the v1 runner's documented loud-ABORT path for
    # worker-killed-mid-job; the test would not get an audit row if
    # fetch_output raised (the runner doesn't wrap fetch_output in
    # try/except — exceptions propagate without a row).
    healthy_a = _ChaosTransport(fetch_bytes=b"cell-A-original-output\n")
    killed_b = _ChaosTransport(fetch_bytes=None)

    m_a, status_a = _run_one_cell(
        strategy=s, symbol=sy, timeframe=tf_a,
        args=_args(run_id=run_id, resume=False), transport=healthy_a,
        output_root=output_root, **_common_kwargs(),
    )
    assert status_a == "dispatched"
    assert m_a is not None
    assert m_a.output_path is not None
    cell_a_path = Path(m_a.output_path)
    cell_a_bytes_before = cell_a_path.read_bytes()

    with pytest.raises(BundleTransportError):
        _run_one_cell(
            strategy=s, symbol=sy, timeframe=tf_b,
            args=_args(run_id=run_id, resume=False), transport=killed_b,
            output_root=output_root, **_common_kwargs(),
        )

    # Cell B has no manifest (killed mid-job).
    assert not (output_root / cid_b / "manifest.json").exists(), (
        "Cell B was killed mid-job — no terminal manifest should be written"
    )
    # Cell A's manifest from phase 1 is untouched.
    assert (output_root / cid_a / "manifest.json").is_file()

    # Audit row: output_missing for cell B (loud ABORT log).
    rows = _read_skipped_rows(output_root)
    kill_rows = [
        r for r in rows
        if r.get("cell_id") == cid_b and r.get("reason") == "output_missing"
    ]
    assert len(kill_rows) == 1, (
        f"expected exactly one output_missing audit row for cell B; "
        f"got {kill_rows!r}"
    )
    assert kill_rows[0]["expected"] == "non-empty bytes"

    # Phase 2: --resume. Cell A should skip; cell B should re-execute.
    fresh_a = _ChaosTransport(fetch_bytes=b"cell-A-original-output\n")
    fresh_b = _ChaosTransport(fetch_bytes=b"cell-B-FRESH-after-kill\n")

    m_a_after, status_a_after = _run_one_cell(
        strategy=s, symbol=sy, timeframe=tf_a,
        args=_args(run_id=run_id, resume=True), transport=fresh_a,
        output_root=output_root, **_common_kwargs(),
    )
    m_b_after, status_b_after = _run_one_cell(
        strategy=s, symbol=sy, timeframe=tf_b,
        args=_args(run_id=run_id, resume=True), transport=fresh_b,
        output_root=output_root, **_common_kwargs(),
    )

    # Cell A: skipped, byte-identical output, transport NOT re-called.
    assert status_a_after == "skipped_resume", (
        f"cell A should skip_resume; got {status_a_after!r}"
    )
    assert fresh_a.push_calls == [], (
        "skipped cell must NOT re-call push_bundle on resume"
    )
    assert fresh_a.fetch_calls == [], (
        "skipped cell must NOT re-call fetch_output on resume"
    )
    assert cell_a_path.read_bytes() == cell_a_bytes_before, (
        "skipped cell's output must be byte-identical (no re-fetch)"
    )

    # Cell B: re-dispatched, fresh output, transport WAS called.
    assert status_b_after == "dispatched", (
        f"killed cell B must re-execute on resume; got {status_b_after!r}"
    )
    assert fresh_b.push_calls == ["deadbeef"], (
        "killed cell B must re-call push_bundle on resume"
    )
    assert fresh_b.fetch_calls == [cid_b], (
        "killed cell B must re-call fetch_output on resume"
    )
    assert m_b_after is not None
    assert m_b_after.output_path is not None
    cell_b_path = Path(m_b_after.output_path)
    assert cell_b_path.is_file()
    assert cell_b_path.read_bytes() == b"cell-B-FRESH-after-kill\n"


# ---------------------------------------------------------------------------
# Scenario 2 — Network/transport interruption mid-dispatch → local fallback,
# no partial manifest, no ABORT audit row.
# ---------------------------------------------------------------------------


def test_scenario2_transport_loss_falls_back_without_audit_row(
    tmp_path: Path,
) -> None:
    """Pre-matrix gate scenario 2.

    ``WorktreeUnreachableError`` on ``push_bundle`` triggers the broad
    ``BundleTransportError`` handler in ``_run_one_cell`` — local-fallback
    path writes the manifest with ``local_fallback=true`` and emits a
    ``scorecard.json``. ``dispatch_skipped.jsonl`` is reserved for
    ABORT-class faults; a graceful fallback writes no row.

    This complements ``test_main_default_mode_runs_local_fallback``
    (CLI-level integration) by asserting the boundary contract:
    - no partial manifest before the fallback (atomic write guarantees
      either fully present with ``local_fallback=true`` or absent);
    - ``v1_stub=true`` flag in the emitted scorecard so downstream
      consumers cannot ingest v1 metrics as real.
    """
    output_root = tmp_path / "chaos-s2"

    unreachable = _ChaosTransport(
        raise_on_push=WorktreeUnreachableError("port-8877 closed"),
    )

    for strategy, symbol, tf in SMOKE_MATRIX:
        m, status = _run_one_cell(
            strategy=strategy, symbol=symbol, timeframe=tf,
            args=_args(run_id="chaos-s2", resume=False),
            transport=unreachable,
            output_root=output_root,
            **_common_kwargs(),
        )
        assert status == "local_fallback", (
            f"{strategy}/{symbol}/{tf}: expected local_fallback, "
            f"got {status!r}"
        )
        assert m is not None
        assert m.local_fallback is True
        assert m.exit_code == 0
        assert m.finished_at is not None
        assert m.output_path is not None
        scorecard = Path(m.output_path)
        assert scorecard.name == "scorecard.json", (
            f"local-fallback output must be scorecard.json; got {scorecard.name}"
        )
        assert scorecard.is_file()
        payload = json.loads(scorecard.read_text())
        assert payload["local_fallback"] is True
        assert payload["v1_stub"] is True, (
            "v1_stub=true flag must be set so downstream cannot ingest "
            "v1 metrics as real PnL (Tomoe cycle-3 sign-off)"
        )

    # No audit row: fallback is graceful, not loud ABORT.
    jsonl_path = output_root / "dispatch_skipped.jsonl"
    assert not jsonl_path.exists(), (
        f"local-fallback path must NOT write dispatch_skipped.jsonl "
        f"(fallback is graceful, not loud ABORT); file exists at {jsonl_path}"
    )


# ---------------------------------------------------------------------------
# Scenario 3 — Version-skew rejection (worker SHA mismatch) → ABORT,
# no fallback manifest, audit row in dispatch_skipped.jsonl.
# ---------------------------------------------------------------------------


def test_scenario3_worker_sha_mismatch_writes_audit_row_and_aborts(
    tmp_path: Path,
) -> None:
    """Pre-matrix gate scenario 3.

    Worker reports a ``WorkerCell.sha256`` that differs from the
    dispatcher's ``bundle_sha``. Trust boundary violation routes through
    ``CodeSHARejectedError`` semantics: audit row written BEFORE the
    raise, no manifest, no fallback execution. ``fetch_output`` is never
    called — the ABORT happens at the post-push_bundle SHA check.
    """
    output_root = tmp_path / "chaos-s3"

    WRONG_SHA = "WRONG-SHA-VS-DISPATCHER-EXPECTED"
    mismatched = _ChaosTransport(
        cell_to_return=WorkerCell(
            path="/tmp/ayumi-offload/s3/bundle",  # noqa: S108 — descriptive
            sha256=WRONG_SHA,
        ),
        fetch_bytes=b"never-fetched\n",  # should never reach fetch_output
    )

    strategy, symbol, tf = SMOKE_MATRIX[0]
    cid = _derive_cell_id(strategy, symbol, tf)

    with pytest.raises(CodeSHARejectedError) as excinfo:
        _run_one_cell(
            strategy=strategy, symbol=symbol, timeframe=tf,
            args=_args(run_id="chaos-s3", resume=False),
            transport=mismatched,
            output_root=output_root,
            **_common_kwargs(),
        )

    # Exception message must cite both expected and actual SHAs.
    msg = str(excinfo.value)
    assert "deadbeef" in msg, (
        f"CodeSHARejectedError must cite expected SHA; got {msg!r}"
    )
    assert WRONG_SHA in msg, (
        f"CodeSHARejectedError must cite worker SHA; got {msg!r}"
    )

    # Audit row written BEFORE the raise.
    rows = _read_skipped_rows(output_root)
    skew_rows = [
        r for r in rows
        if r.get("cell_id") == cid and r.get("reason") == "code_skew"
    ]
    assert len(skew_rows) == 1, (
        f"expected exactly one code_skew audit row; got {skew_rows!r}"
    )
    row = skew_rows[0]
    assert row["expected"] == "deadbeef"
    assert row["actual"] == WRONG_SHA
    assert row.get("validation") == "post-push_bundle"

    # No manifest, no scorecard (ABORT is fail-loud, no fallback).
    assert not (output_root / cid / "manifest.json").exists(), (
        "manifest was written — wrong-SHA must ABORT (no fallback manifest)"
    )
    assert not (output_root / cid / "scorecard.json").exists()

    # fetch_output was NOT called (ABORT happens at post-push_bundle SHA check).
    assert mismatched.fetch_calls == [], (
        "ABORT-on-SHA-mismatch must skip fetch_output entirely"
    )


# ---------------------------------------------------------------------------
# Scenario 4 — Poisoned-output detection (tamper one output hash) → resume
# re-executes the tampered cell.
# ---------------------------------------------------------------------------


def test_scenario4_tampered_output_hash_resume_writes_audit_row(
    tmp_path: Path,
) -> None:
    """Pre-matrix gate scenario 4.

    After a successful dispatch, the manifest's ``output_hash`` is
    overwritten with a bogus value. On ``--resume``, the runner
    recomputes SHA-256(output_path) and compares to the manifest's
    ``output_hash``. Mismatch:
    - Writes an ``output_hash_mismatch`` audit row with both expected
      (manifest) and actual (computed) values.
    - Re-dispatches the cell (push_bundle + fetch_output called again).
    - Persists the fresh manifest with the correct (re-computed)
      ``output_hash`` on disk.
    """
    output_root = tmp_path / "chaos-s4"

    strategy, symbol, tf = SMOKE_MATRIX[0]
    cid = _derive_cell_id(strategy, symbol, tf)

    # Phase 1: dispatch cleanly.
    clean = _ChaosTransport(fetch_bytes=b"clean-output\n")
    m_clean, status_clean = _run_one_cell(
        strategy=strategy, symbol=symbol, timeframe=tf,
        args=_args(run_id="chaos-s4", resume=False),
        transport=clean,
        output_root=output_root,
        **_common_kwargs(),
    )
    assert status_clean == "dispatched"
    assert m_clean is not None
    real_hash = m_clean.output_hash
    manifest_path = output_root / cid / "manifest.json"
    assert real_hash is not None
    assert real_hash != "0" * 64

    # Phase 2: tamper with output_hash on disk.
    tampered = json.loads(manifest_path.read_text())
    tampered["output_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(tampered, indent=2, sort_keys=True))

    # Phase 3: --resume with a fresh transport → re-executes.
    fresh = _ChaosTransport(fetch_bytes=b"clean-output\n")
    m_after, status_after = _run_one_cell(
        strategy=strategy, symbol=symbol, timeframe=tf,
        args=_args(run_id="chaos-s4", resume=True),
        transport=fresh,
        output_root=output_root,
        **_common_kwargs(),
    )

    # Audit row written BEFORE the re-dispatch.
    rows = _read_skipped_rows(output_root)
    tamper_rows = [
        r for r in rows
        if r.get("cell_id") == cid and r.get("reason") == "output_hash_mismatch"
    ]
    assert len(tamper_rows) == 1, (
        f"expected one output_hash_mismatch row; got {tamper_rows!r}"
    )
    assert tamper_rows[0]["expected"] == "0" * 64
    assert tamper_rows[0]["actual"] == real_hash

    # Cell re-executed (push_bundle + fetch_output called again).
    assert status_after == "dispatched"
    assert fresh.push_calls == ["deadbeef"]
    assert fresh.fetch_calls == [cid]
    assert m_after is not None
    assert m_after.output_hash == real_hash

    # Manifest on disk has the CORRECT (re-computed) hash again.
    payload = json.loads(manifest_path.read_text())
    assert payload["output_hash"] == real_hash, (
        "manifest must be re-written with the correct output_hash"
    )
    out_p = Path(payload["output_path"])
    assert out_p.is_file()
    actual = hashlib.sha256(out_p.read_bytes()).hexdigest()
    assert actual == real_hash, (
        "output_path file bytes must hash to the manifest's output_hash"
    )
