"""Unit tests for ``BundleTransport`` ABC + error hierarchy + ``Port8877StubTransport``.

Coverage:
- ``WorkerCell``: ``frozen=True`` (immutable by design).
- Error hierarchy: ``WorktreeUnreachableError`` /
  ``CodeSHARejectedError`` / ``BundleTooLargeError`` are all subclasses of
  ``BundleTransportError`` (per Tomoe's explicit endorsement at
  checkpoint 2: ``WorktreeUnreachable`` → fallback, ``CodeSHARejected``
  → ABORT never fallback, ``BundleTooLarge`` → fail loud).
- ``Port8877StubTransport``:
  * default mode (no ``simulate_success``): ``push_bundle`` raises
    ``WorktreeUnreachableError`` (drives the local-fallback path in
    production).
  * ``simulate_success=True``: ``push_bundle`` returns a synthetic
    ``WorkerCell`` whose ``sha256`` equals the expected input (preserves
    the SHA-contract for ABC contract tests).
  * ``fetch_output``: v1 stub returns ``None`` (no real wire).
"""

from __future__ import annotations

import dataclasses

import pytest

from offload.transport import (
    BundleTransport,
    BundleTransportError,
    BundleTooLargeError,
    CodeSHARejectedError,
    Port8877StubTransport,
    WorktreeUnreachableError,
    WorkerCell,
)


# ---------------------------------------------------------------------------
# WorkerCell dataclass (frozen)
# ---------------------------------------------------------------------------


def test_worker_cell_is_frozen() -> None:
    """``WorkerCell`` is ``frozen=True``; attribute assignment raises."""
    cell = WorkerCell(path="/tmp/ayumi-offload/r1/bundle.simulated", sha256="deadbeef")
    with pytest.raises(dataclasses.FrozenInstanceError):
        cell.sha256 = "newhash"  # type: ignore[misc]


def test_worker_cell_stores_path_and_sha256() -> None:
    """Constructor accepts both attributes; round-trip via equality."""
    cell = WorkerCell(path="/foo", sha256="abc")
    assert cell.path == "/foo"
    assert cell.sha256 == "abc"
    assert cell == WorkerCell(path="/foo", sha256="abc")


# ---------------------------------------------------------------------------
# Error hierarchy (Q2 load-bearing — Tomoe explicitly endorsed at check 2)
# ---------------------------------------------------------------------------


def test_bundle_transport_error_is_exception_base() -> None:
    """``BundleTransportError`` subclasses ``Exception``."""
    assert issubclass(BundleTransportError, Exception)


def test_worktree_unreachable_error_is_bundle_transport_error() -> None:
    """Subclass chain: ``WorktreeUnreachableError -> BundleTransportError``."""
    assert issubclass(WorktreeUnreachableError, BundleTransportError)


def test_code_sha_rejected_error_is_bundle_transport_error() -> None:
    """Subclass chain: ``CodeSHARejectedError -> BundleTransportError``."""
    assert issubclass(CodeSHARejectedError, BundleTransportError)


def test_bundle_too_large_error_is_bundle_transport_error() -> None:
    """Subclass chain: ``BundleTooLargeError -> BundleTransportError``."""
    assert issubclass(BundleTooLargeError, BundleTransportError)


# Concrete causal semantic — Q2/Q1 contract:
#   * WorktreeUnreachable → local fallback (caught at the runner)
#   * CodeSHARejected     → ABORT (caught at the runner, re-raised)
#   * BundleTooLarge      → fail loud (propagated up)


# ---------------------------------------------------------------------------
# BundleTransport ABC (abstract methods present)
# ---------------------------------------------------------------------------


def test_bundle_transport_cannot_be_instantiated_directly() -> None:
    """ABC: ``BundleTransport()`` raises ``TypeError`` (abstract members)."""
    with pytest.raises(TypeError):
        BundleTransport()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Port8877StubTransport behavior
# ---------------------------------------------------------------------------


def test_stub_raises_worktree_unreachable_when_simulate_false(tmp_path) -> None:
    """Default mode: ``push_bundle`` raises ``WorktreeUnreachableError``."""
    from pathlib import Path

    stub = Port8877StubTransport(simulate_success=False)
    with pytest.raises(WorktreeUnreachableError):
        stub.push_bundle(
            run_id="r1", bundle_path=Path("/no-such-bundle"),
            expected_sha256="abc",
        )


def test_stub_raises_are_caught_by_bundle_transport_error_handler() -> None:
    """WorktreeUnreachable → can be caught as BundleTransportError (isinstance)."""
    from pathlib import Path

    stub = Port8877StubTransport(simulate_success=False)
    try:
        stub.push_bundle(run_id="r1", bundle_path=Path("/x"),
                         expected_sha256="abc")
    except BundleTransportError:
        pass  # runner's except BundleTransportError clause catches it
    except WorktreeUnreachableError:
        pass  # more-specific catch would also work


def test_stub_returns_synthetic_worker_cell_when_simulate_true() -> None:
    """``simulate_success=True`` returns a synthetic ``WorkerCell``."""
    from pathlib import Path

    expected_sha = "deadbeef0001"
    stub = Port8877StubTransport(simulate_success=True)
    cell = stub.push_bundle(
        run_id="r1-sim", bundle_path=Path("/whatever"),
        expected_sha256=expected_sha,
    )
    assert isinstance(cell, WorkerCell)
    assert cell.sha256 == expected_sha  # SHA contract preserved
    assert cell.path.endswith(f"/{expected_sha}/bundle.simulated") or \
        "bundle.simulated" in cell.path  # synthetic-path signal


def test_stub_synthetic_path_uses_run_id(tmp_path) -> None:
    """The synthetic ``WorkerCell.path`` references the run_id (for traceability)."""
    from pathlib import Path

    stub = Port8877StubTransport(simulate_success=True)
    cell = stub.push_bundle(
        run_id="my-traceable-run", bundle_path=Path("/ignore-me"),
        expected_sha256="cafebabe",
    )
    assert "my-traceable-run" in cell.path


def test_stub_fetch_output_returns_none() -> None:
    """v1 stub doesn't implement output retrieval — always ``None``."""
    from pathlib import Path

    stub = Port8877StubTransport(simulate_success=False)
    assert stub.fetch_output(run_id="r1", cell_id="any-cell") is None
    stub_sim = Port8877StubTransport(simulate_success=True)
    assert stub_sim.fetch_output(run_id="r1", cell_id="any-cell") is None


def test_stub_is_subclass_of_bundle_transport() -> None:
    """``Port8877StubTransport`` is an ABC subclass (instantiable)."""
    assert issubclass(Port8877StubTransport, BundleTransport)
    # And both concrete forms instantiate fine (no abstract leakage).
    Port8877StubTransport(simulate_success=False)
    Port8877StubTransport(simulate_success=True)
