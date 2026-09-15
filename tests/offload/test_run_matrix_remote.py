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
import json
import sys
import threading
from pathlib import Path

from offload.run_matrix_remote import (
    SMOKE_MATRIX,
    _run_one_cell,
    main,
)
from offload.seed import cell_id as _derive_cell_id


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
    rc = _invoke(
        ["--run-id", "smoke-fb", "--output-root", str(output_root)]
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
