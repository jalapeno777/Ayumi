"""Integration tests for ``run_matrix_remote`` (the CLI dispatch loop).

Coverage:
- ``main()`` with ``--simulate-transport``: 2 cells dispatched via the
  Port8877StubTransport simulate path.
- ``main()`` default mode (no ``--simulate``): Port8877StubTransport
  raises ``WorktreeUnreachableError`` on real invoke, forcing local
  fallback for both cells + scorecard.json emission.
- ``main() --resume``: second run skips cells with terminal manifests
  (Q4.b exactly-once re-run idempotency at the CLI level).
- ``_run_one_cell`` parallel-resume: two threads racing on the same
  matrix → per-cell exactly-once dispatch (Q4.c; this is the test
  Tomoe will look at first per Ava's note).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest
from offload.run_matrix_remote import (
    SMOKE_MATRIX,
    _run_one_cell,
    main,
)
from offload.seed import cell_id as _derive_cell_id
from offload.transport import (
    BundleTooLargeError,
    BundleTransport,
    CodeSHARejectedError,
    WorkerCell,
    WorktreeUnreachableError,
)


def _invoke(argv: list[str]):
    """Invoke ``main()`` directly (avoids subprocess overhead; function
    signature accepts a custom argv list)."""
    return main(argv)


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def test_main_simulate_mode_dispatches_two_cells(tmp_path: Path, capsys) -> None:
    """Smoke 2-cell matrix under ``--simulate-transport`` → 2 dispatched."""
    output_root = tmp_path / "smoke-sim"
    rc = _invoke(
        ["--run-id", "smoke-sim", "--output-root", str(output_root),
         "--simulate-transport"]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "2/2 cells" in captured.out
    assert "2 dispatched" in captured.out

    # Each cell produced a manifest under its cell_id directory.
    # --output-root <tmp_path/smoke-sim> + run_id 'smoke-sim' resolves
    # to tmp_path/smoke-sim/smoke-sim/{cell_id}/manifest.json.
    expected_cids = {_derive_cell_id(*c) for c in SMOKE_MATRIX}
    manifest_paths = sorted((output_root / "smoke-sim").glob("*/manifest.json"))
    assert len(manifest_paths) == 2
    for mp in manifest_paths:
        assert mp.parent.name in expected_cids
        payload = json.loads(mp.read_text())
        assert payload["cell_id"] in expected_cids
        assert payload["finished_at"] is not None  # Q4.a terminal state
        assert payload["exit_code"] == 0
        assert payload["local_fallback"] is False


def test_main_default_mode_runs_local_fallback(tmp_path: Path, capsys) -> None:
    """Default mode (no ``--simulate``) → stub raises → local fallback for both cells."""
    output_root = tmp_path / "smoke-fb"
    # --transport=stub keeps the v1.0 default-mode behavior (raises on real
    # invoke → local fallback). Default --transport is now 'node' (c3134271).
    rc = _invoke(
        ["--run-id", "smoke-fb", "--output-root", str(output_root),
         "--transport", "stub"]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "2/2 cells" in captured.out
    # Cycle-3 main() uses a breakdown dict; the substring is
    # "local_fallback" (underscore, status value) not "local fallback" (space).
    assert "local_fallback" in captured.out

    # Both cells should have both manifest.json AND scorecard.json
    # (local-fallback path writes the scorecard deterministically).
    # Output root resolves to <base> / <run_id>: tmp_path/smoke-fb/smoke-fb/.
    expected_cids = {_derive_cell_id(*c) for c in SMOKE_MATRIX}
    for cid in expected_cids:
        cell_dir = output_root / "smoke-fb" / cid
        assert (cell_dir / "manifest.json").is_file()
        assert (cell_dir / "scorecard.json").is_file()

        manifest = json.loads((cell_dir / "manifest.json").read_text())
        assert manifest["local_fallback"] is True
        assert manifest["exit_code"] == 0
        assert manifest["output_path"].endswith("scorecard.json")

        scorecard = json.loads((cell_dir / "scorecard.json").read_text())
        assert scorecard["local_fallback"] is True
        assert scorecard["v1_stub"] is True  # placeholder, NOT real PnL


def test_main_resume_skips_terminal_manifests(tmp_path: Path, capsys) -> None:
    """``--resume`` on a matrix where manifests already exist → skipped_resume count > 0."""
    output_root = tmp_path / "smoke-rs"
    # First run writes manifests.
    rc1 = _invoke(
        ["--run-id", "smoke-rs", "--output-root", str(output_root),
         "--simulate-transport"]
    )
    assert rc1 == 0
    capsys.readouterr()  # drain

    # Second run with --resume reuses the existing manifests.
    rc2 = _invoke(
        ["--run-id", "smoke-rs", "--output-root", str(output_root),
         "--simulate-transport", "--resume"]
    )
    assert rc2 == 0
    captured = capsys.readouterr()
    assert "2 skipped_resume" in captured.out


def test_main_output_root_env_fallback(tmp_path: Path, monkeypatch) -> None:
    """``AYUMI_OFFLOAD_ROOT`` env precedence per Q6 flag (CLI flag > env > default)."""
    monkeypatch.setenv("AYUMI_OFFLOAD_ROOT", str(tmp_path / "from-env"))
    # No --output-root → env wins.
    rc = _invoke(
        ["--run-id", "env-test", "--simulate-transport"]
    )
    assert rc == 0
    # Manifests land under tmp_path/from-env/env-test/ (NOT tmp_path/env-test/)
    assert (tmp_path / "from-env" / "env-test").is_dir()
    assert len(list((tmp_path / "from-env" / "env-test").glob("*/manifest.json"))) == 2


# ---------------------------------------------------------------------------
# The CRITICAL parallel-resume reproducer (Tomoe's first-look test)
# ---------------------------------------------------------------------------


def test_parallel_resume_exactly_once(tmp_path: Path, capsys) -> None:
    """Q4.c exactly-once dispatch under parallel ``--resume`` (the test Tomoe will look at first).

    *** Critical reproducer of commit 55d4c2ba's ``per_cell_lock`` hardening.

    Design: two threads race for the SAME single cell. ``barrier.wait()``
    releases both at the same instant; both then race to acquire
    ``per_cell_lock(cell_out)``. The winner's flock call succeeds; the
    loser's flock call returns ``EWOULDBLOCK`` (BlockingIOError) which
    ``per_cell_lock`` converts to ``RuntimeError``; the cycle-4a-pre fix
    in ``_run_one_cell`` catches that and converts to ``"skipped_resume"`` +
    stderr ``"warn: cell ... lock contended ..."`` line.

    Single-cell focus is intentional: with simulate mode the
    per_cell_lock window is microseconds — having both threads iterate
    the full 2-cell matrix reduces to sequential dispatch (one thread
    wins cell A, finishes, releases; the other finds the lock free for
    cell A; same for cell B). The single-cell design holds both threads
    at the same lock at the SAME instant via the barrier, forcing the
    race the contract describes.

    Invariant: ``sorted([runner_a.status, runner_b.status]) ==
    ["dispatched", "skipped_resume"]``. Stderr ``warn: cell`` count
    ``>= 1`` (Q4.c observability).
    """
    output_root = tmp_path / "parallel-smoke"
    output_root.mkdir(parents=True)

    ns = argparse.Namespace(
        simulate_transport=True, run_id="parallel-smoke", resume=False
    )

    # Single-cell race (deterministic; see docstring).
    s, sy, tf = SMOKE_MATRIX[0]
    from offload.transport import Port8877StubTransport as _Stub

    results_a: list[str] = []
    results_b: list[str] = []

    barrier = threading.Barrier(2, timeout=10)

    def runner(results: list, label: str) -> None:
        barrier.wait()  # both threads at the fence; released together
        trans = _Stub(simulate_success=True)
        _m, status = _run_one_cell(
            strategy=s, symbol=sy, timeframe=tf,
            args=ns, transport=trans,
            output_root=output_root,
            git_sha="e97cd420e0b6225d42728bc91af9dcca86c7f21e",
            env_lock_hash_val="9123e0ab" * 8,
            env_lock_files_names=[
                "requirements.txt", "requirements-duckdb.txt",
            ],
            bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive test fixture (no FS op; same family as cycle 1 fca6a63b fix)
            bundle_sha="deadbeef",
            bundle_files=[],
        )
        results.append(status)
        print(f"[runner {label}] {s}/{sy}/{tf} -> {status}", file=sys.stderr)

    ta = threading.Thread(target=runner, args=(results_a, "A"))
    tb = threading.Thread(target=runner, args=(results_b, "B"))
    ta.start()
    tb.start()
    ta.join(timeout=30)
    tb.join(timeout=30)
    assert not ta.is_alive() and not tb.is_alive(), "thread hang"

    # Each runner recorded exactly one status.
    assert len(results_a) == 1
    assert len(results_b) == 1
    status_a = results_a[0]
    status_b = results_b[0]

    # The contract: per-cell exactly one dispatched + one skipped_resume.
    pair = sorted([status_a, status_b])
    assert pair == ["dispatched", "skipped_resume"], (
        f"single-cell race: expected ['dispatched', 'skipped_resume'], "
        f"got {pair} (runner_a={status_a!r}, runner_b={status_b!r})"
    )

    # Q4.c observability: stderr "warn: cell ..." line from the loser.
    captured = capsys.readouterr()
    warn_count = sum(
        1 for line in captured.err.splitlines() if line.startswith("warn: cell")
    )
    assert warn_count >= 1, (
        f"expected >=1 'warn: cell' stderr line, got {warn_count!r} "
        f"from stderr={captured.err!r}"
    )


# ---------------------------------------------------------------------------
# Import the symbol we use as a transport alias (avoids repeating the long
# qualified name in the test function; ruff E402 tolerated because the
# import is test-scope and the comment is non-blank).
# ---------------------------------------------------------------------------
from offload.transport import Port8877StubTransport  # noqa: E402,F401  # used at module top of nested func

# ---------------------------------------------------------------------------
# REWORK round: focused regression tests for Rin findings 1-4 + AC1 sentinel.
# Each test exercises a specific trust-boundary semantic that the production
# fix enforces.
# ---------------------------------------------------------------------------


class _FakeTransport(BundleTransport):
    """Configurable fake for trust-boundary testing.

    raise_with: exception to raise from push_bundle (None = no raise)
    cell_to_return: WorkerCell to return from push_bundle (when raise_with is None)
    fetch_bytes: bytes to return from fetch_output (None = return None)
    attempts: list tracking push_bundle calls (for AC1 sentinel)
    """

    def __init__(
        self,
        *,
        raise_with: Exception | None = None,
        cell_to_return: WorkerCell | None = None,
        fetch_bytes: bytes | None = None,
    ) -> None:
        self._raise_with = raise_with
        self._cell_to_return = cell_to_return
        self._fetch_bytes = fetch_bytes
        self.attempts: list[str] = []

    def push_bundle(
        self, run_id: str, bundle_path, expected_sha256: str
    ) -> WorkerCell:
        self.attempts.append(expected_sha256)
        if self._raise_with is not None:
            raise self._raise_with
        if self._cell_to_return is not None:
            return self._cell_to_return
        raise WorktreeUnreachableError("fake stub default")

    def fetch_output(self, run_id: str, cell_id: str) -> bytes | None:
        return self._fetch_bytes


def test_bundle_too_large_error_fails_loud_no_fallback_manifest(
    tmp_path: Path,
) -> None:
    """Fix #1 (Rin): BundleTooLargeError must FAIL LOUD, no fallback manifest.

    A BundleTransportError subclass that doesn't have an explicit fail-loud
    clause (CodeSHARejectedError) must be caught separately from the broad
    BundleTransportError handler — otherwise it'd silently trigger the
    local-fallback path, violating the locked BundleTooLarge → no-fallback
    semantic (Tomoe explicit at checkpoint 2 sign-off).
    """
    fake = _FakeTransport(raise_with=BundleTooLargeError("size cap exceeded"))
    args = argparse.Namespace(
        simulate_transport=False, run_id="fix1-test", resume=False
    )
    output_root = tmp_path / "fix1"

    with pytest.raises(BundleTooLargeError):
        _run_one_cell(
            strategy="q1_mw_formation", symbol="GBPUSD", timeframe="M5",
            args=args, transport=fake,
            output_root=output_root,
            git_sha="e97cd420e0b6225d42728bc91af9dcca86c7f21e",
            env_lock_hash_val="9123e0ab" * 8,
            env_lock_files_names=["requirements.txt", "requirements-duckdb.txt"],
            bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive test fixture (no FS op; same family as cycle 5 2656b873 fix)
            bundle_sha="deadbeef",
            bundle_files=[],
        )

    cid = _derive_cell_id("q1_mw_formation", "GBPUSD", "M5")
    assert not (output_root / cid / "manifest.json").exists(), (
        "manifest was written — BundleTooLarge should be fail-loud "
        "(no fallback manifest on the ABORT path)"
    )


def test_worker_cell_sha_mismatch_routes_through_codesharejected(
    tmp_path: Path,
) -> None:
    """Fix #2 (Rin): WorkerCell.sha256 must be compared against bundle_sha.

    A transport returning a WorkerCell with the wrong sha256 (silently
    tampering or a corrupted worker) must be caught and routed through
    CodeSHARejectedError semantics (audit row + ABORT). Pre-fix, the
    return value was discarded → wrong-SHA worker succeeded silently.
    """
    fake = _FakeTransport(
        cell_to_return=WorkerCell(
            path="/tmp/ayumi-offload/fix2/bundle",  # noqa: S108
            sha256="WRONG-SHA-VS-DISPATCHER-EXPECTED",
        )
    )
    args = argparse.Namespace(
        simulate_transport=False, run_id="fix2-test", resume=False
    )
    output_root = tmp_path / "fix2"

    with pytest.raises(CodeSHARejectedError) as excinfo:
        _run_one_cell(
            strategy="q1_mw_formation", symbol="GBPUSD", timeframe="M5",
            args=args, transport=fake,
            output_root=output_root,
            git_sha="e97cd420e0b6225d42728bc91af9dcca86c7f21e",
            env_lock_hash_val="9123e0ab" * 8,
            env_lock_files_names=["requirements.txt", "requirements-duckdb.txt"],
            bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive test fixture (no FS op; same family as cycle 5 2656b873 fix)
            bundle_sha="deadbeef",
            bundle_files=[],
        )

    msg = str(excinfo.value)
    assert "deadbeef" in msg  # expected
    assert "WRONG-SHA" in msg  # actual

    cid = _derive_cell_id("q1_mw_formation", "GBPUSD", "M5")
    assert not (output_root / cid / "manifest.json").exists(), (
        "manifest was written — wrong-SHA must ABORT (no fallback manifest)"
    )


def test_simulate_mode_populates_output_hash_and_path(
    tmp_path: Path,
) -> None:
    """Fix #3 (Rin): successful dispatch must terminalize with output_hash.

    Pre-fix, the manifest had output_hash=None / output_path=None —
    fetch_output() was never called. Per AC4 ("manifests validate:
    exit_code + output_hash + env_lock_hash + git_sha present"), every
    successful dispatch must carry output_path + output_hash computed
    from the worker's actual output bytes.
    """
    fake = _FakeTransport(
        cell_to_return=WorkerCell(
            path="/tmp/ayumi-offload/fix3/bundle",  # noqa: S108
            sha256="deadbeef",
        ),
        fetch_bytes=b"simulated-worker-output:fix3-test:CID\n",
    )
    args = argparse.Namespace(
        simulate_transport=False, run_id="fix3-test", resume=False
    )
    output_root = tmp_path / "fix3"

    m, status = _run_one_cell(
        strategy="q1_mw_formation", symbol="GBPUSD", timeframe="M5",
        args=args, transport=fake,
        output_root=output_root,
        git_sha="e97cd420e0b6225d42728bc91af9dcca86c7f21e",
        env_lock_hash_val="9123e0ab" * 8,
        env_lock_files_names=["requirements.txt", "requirements-duckdb.txt"],
        bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive test fixture (no FS op; same family as cycle 5 2656b873 fix)
        bundle_sha="deadbeef",
        bundle_files=[],
    )

    assert status == "dispatched"
    assert m is not None
    assert m.output_path is not None, "AC4: output_path must be populated"
    assert m.output_hash is not None, "AC4: output_hash must be populated"
    assert m.finished_at is not None
    assert m.exit_code == 0

    out_p = Path(m.output_path)
    assert out_p.is_file(), "output file must be persisted for --resume re-verify"
    actual_hash = hashlib.sha256(out_p.read_bytes()).hexdigest()
    assert actual_hash == m.output_hash


def test_resume_reruns_on_tampered_output_hash(
    tmp_path: Path,
) -> None:
    """Fix #4 (Rin): --resume re-validates output exists + SHA matches.

    Pre-fix, --resume skipped solely on (manifest.json exists + finished_at
    not None). Tampered output_hash would slip through. Post-fix, skip is
    permitted ONLY when output_path file exists AND its SHA matches the
    manifest's output_hash. Otherwise the runner logs a skip reason via
    dispatch_skipped.jsonl and falls through to fresh run.
    """
    fake = _FakeTransport(
        cell_to_return=WorkerCell(
            path="/tmp/ayumi-offload/fix4/bundle",  # noqa: S108
            sha256="deadbeef",
        ),
        fetch_bytes=b"original-output\n",
    )
    args = argparse.Namespace(
        simulate_transport=False, run_id="fix4-test", resume=False
    )
    output_root = tmp_path / "fix4"
    _run_one_cell(
        strategy="q1_mw_formation", symbol="GBPUSD", timeframe="M5",
        args=args, transport=fake,
        output_root=output_root,
        git_sha="e97cd420e0b6225d42728bc91af9dcca86c7f21e",
        env_lock_hash_val="9123e0ab" * 8,
        env_lock_files_names=["requirements.txt", "requirements-duckdb.txt"],
        bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive test fixture (no FS op; same family as cycle 5 2656b873 fix)
        bundle_sha="deadbeef",
        bundle_files=[],
    )

    # Tamper with the manifest: change output_hash to bogus.
    cid = _derive_cell_id("q1_mw_formation", "GBPUSD", "M5")
    manifest_path = output_root / cid / "manifest.json"
    tampered = json.loads(manifest_path.read_text())
    real_hash = tampered["output_hash"]
    tampered["output_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(tampered, indent=2, sort_keys=True))
    assert real_hash != tampered["output_hash"]

    # --resume: should detect tamper and force a fresh re-run.
    args2 = argparse.Namespace(
        simulate_transport=False, run_id="fix4-test", resume=True
    )
    fresh_fake = _FakeTransport(
        cell_to_return=WorkerCell(
            path="/tmp/ayumi-offload/fix4/bundle",  # noqa: S108
            sha256="deadbeef",
        ),
        fetch_bytes=b"original-output\n",
    )
    m_after, status_after = _run_one_cell(
        strategy="q1_mw_formation", symbol="GBPUSD", timeframe="M5",
        args=args2, transport=fresh_fake,
        output_root=output_root,
        git_sha="e97cd420e0b6225d42728bc91af9dcca86c7f21e",
        env_lock_hash_val="9123e0ab" * 8,
        env_lock_files_names=["requirements.txt", "requirements-duckdb.txt"],
        bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive test fixture (no FS op; same family as cycle 5 2656b873 fix)
        bundle_sha="deadbeef",
        bundle_files=[],
    )
    assert status_after == "dispatched", (
        f"tampered output_hash must force re-run, got status={status_after!r}"
    )

    # Manifest on disk has the CORRECT hash again (overwritten by re-run).
    payload = json.loads(manifest_path.read_text())
    assert payload["output_hash"] == real_hash, (
        "manifest must be re-written with the correct output_hash"
    )


def test_ac1_sentinel_dispatch_attempt_logged_on_fallback(
    tmp_path: Path,
) -> None:
    """AC1 sentinel (Tomoe's gap): dispatch ATTEMPT must be observable
    even on fallback. Without this sentinel, a buggy runner that always
    picks the local path would never trigger the per_cell_lock contention
    path; tests would pass green but the trust boundary is silently
    compromised. The FakeTransport records push_bundle invocations → if
    the runner calls push_bundle at all on every cell, the trust boundary
    is wired.
    """
    fake = _FakeTransport(
        raise_with=WorktreeUnreachableError("simulated worker unreachable")
    )
    args = argparse.Namespace(
        simulate_transport=False, run_id="ac1-test", resume=False
    )
    output_root = tmp_path / "ac1"

    for strategy, symbol, tf in SMOKE_MATRIX:
        _run_one_cell(
            strategy=strategy, symbol=symbol, timeframe=tf,
            args=args, transport=fake,
            output_root=output_root,
            git_sha="e97cd420e0b6225d42728bc91af9dcca86c7f21e",
            env_lock_hash_val="9123e0ab" * 8,
            env_lock_files_names=["requirements.txt", "requirements-duckdb.txt"],
            bundle_path=Path("/tmp/no-bundle"),  # noqa: S108 — descriptive test fixture (no FS op; same family as cycle 5 2656b873 fix)
            bundle_sha="deadbeef",
            bundle_files=[],
        )

    assert len(fake.attempts) == 2, (
        f"AC1 sentinel: expected 2 dispatch attempts (one per cell); "
        f"got {len(fake.attempts)}. If attempts == 0, the runner silently "
        f"picks local without trying the wire."
    )
    assert all(s == "deadbeef" for s in fake.attempts), (
        f"all attempts must carry the expected bundle_sha; got {fake.attempts}"
    )
