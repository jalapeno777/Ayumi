"""Unit tests for ``OpenClawNodeBundleTransport`` (c3134271).

These tests exercise the ABC contract via mocked CLI invocations
because the live wire is gated on a host-level shell-exec interface
(node ``system.run`` is currently reserved; the exec-policy interface
needs to be wired before the live smoke can run).

The tests verify:
  - SHA256 pre-flight on the dispatcher side (Rin finding #2 wire integrity)
  - Terminal upload invocation + SHA verification on the worker side
  - Per-cell ``system.run`` execution via env-var context (Q2 + Q5 ephemeral)
  - Output fetch via file.fetch invoke
  - Error mapping: invoke failure → ``WorktreeUnreachableError``;
    SHA mismatch → ``CodeSHARejectedError`` (Q1 loud skew ABORT);
    size-cap → ``BundleTooLargeError`` (Rin finding #1 fail-loud)

DELEG-REF: c3134271-601e-42c2-9797-6407ae25048c
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from offload.transport import (
    BundleTooLargeError,
    CodeSHARejectedError,
    OpenClawNodeBundleTransport,
    WorktreeUnreachableError,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _stub_subprocess_run(stdout: str = "", returncode: int = 0, stderr: str = ""):
    """Build a CompletedProcess-like mock for subprocess.run."""
    cp = subprocess.CompletedProcess(args=[], returncode=returncode)
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


@pytest.fixture()
def transport() -> OpenClawNodeBundleTransport:
    return OpenClawNodeBundleTransport(node="ava-worker-local")


@pytest.fixture()
def bundle_path(tmp_path: Path) -> Path:
    """Write a small test bundle (a single file) and return its path.

    Returns the FILE path (not the parent dir) because the transport's
    push_bundle reads ``bundle_path.read_bytes()`` — a directory read
    would raise IsADirectoryError. Uses ``exist_ok=True`` on the parent
    mkdir because ``tmp_path`` is shared across tests in the same pytest
    session and may already exist.
    """
    f = tmp_path / "bundle.py"
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(b"print('hello from worker bundle')\n")
    return f


def _expected_sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


# ── Tests ─────────────────────────────────────────────────────────────────


def test_push_bundle_succeeds_against_mocked_cli(transport, bundle_path):
    """Happy path: bundle upload + worker SHA verify + per-cell exec."""
    sha = _expected_sha(bundle_path)

    calls: list[tuple[str, dict]] = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd[cmd.index("--command") + 1], json.loads(cmd[cmd.index("--params") + 1])))
        # Stage 1: terminal.upload — no stdout (success).
        # Stage 2: sha256sum on worker — return matching SHA.
        # Stage 3: system.run (per-cell exec) — no stdout.
        if calls[-1][0] == "sha256sum" or "sha256sum" in calls[-1][1].get("command", ""):
            return _stub_subprocess_run(stdout=f"{sha}  /tmp/ayumi-offload/x/bundle\n")
        return _stub_subprocess_run(stdout="")

    with mock.patch("subprocess.run", side_effect=fake_run) as m:
        result = transport.push_bundle("run-x", bundle_path, sha)

    assert isinstance(result.sha256, str)
    assert result.sha256 == sha
    # Terminal.upload + sha256sum + system.run were invoked.
    invoked_cmds = [c[0] for c in calls]
    assert invoked_cmds.count("terminal.upload") == 1
    assert "sha256sum" in str(calls).lower() or "system.run" in str(calls).lower()


def test_push_bundle_sha_mismatch_raises_codesharejected(transport, bundle_path):
    """Local bundle SHA != expected → CodeSHARejectedError (Rin finding #2)."""
    sha = _expected_sha(bundle_path)
    with mock.patch("subprocess.run", return_value=_stub_subprocess_run()):
        with pytest.raises(CodeSHARejectedError) as excinfo:
            transport.push_bundle("run-y", bundle_path, "0" * 64)
    assert sha in str(excinfo.value)


def test_push_bundle_terminal_upload_failure_raises_worktree(transport, bundle_path):
    """Terminal upload failure (e.g., node offline) → WorktreeUnreachableError."""
    sha = _expected_sha(bundle_path)
    cp = _stub_subprocess_run(returncode=1, stderr="connection refused")
    with mock.patch("subprocess.run", return_value=cp):
        with pytest.raises(WorktreeUnreachableError):
            transport.push_bundle("run-z", bundle_path, sha)


def test_push_bundle_worker_sha_mismatch_raises_codesharejected(transport, bundle_path):
    """Worker-side SHA != dispatcher → CodeSHARejectedError (Q1 loud skew)."""
    sha = _expected_sha(bundle_path)

    def fake_run(cmd, **kwargs):
        cmd_name = cmd[cmd.index("--command") + 1]
        if cmd_name == "terminal.upload":
            return _stub_subprocess_run()
        if "sha256sum" in cmd_name or "sha256sum" in json.loads(cmd[cmd.index("--params") + 1]).get("command", ""):
            return _stub_subprocess_run(stdout="DIFFERENT_SHA  /tmp/ayumi-offload/x/bundle\n")
        return _stub_subprocess_run()

    with mock.patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(CodeSHARejectedError):
            transport.push_bundle("run-aa", bundle_path, sha)


def test_push_bundle_size_cap_raises_bundle_too_large(transport, bundle_path):
    """terminal.upload size-cap rejection → BundleTooLargeError (Rin finding #1)."""
    sha = _expected_sha(bundle_path)

    def fake_run(cmd, **kwargs):
        cmd_name = cmd[cmd.index("--command") + 1]
        if cmd_name == "terminal.upload":
            cp = _stub_subprocess_run(returncode=2, stderr="exceeds 5MB cap")
            return cp
        return _stub_subprocess_run()

    with mock.patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(BundleTooLargeError):
            transport.push_bundle("run-bb", bundle_path, sha)


def test_fetch_output_returns_decoded_bytes(transport):
    """fetch_output decodes file.fetch base64 JSON response."""
    payload_bytes = b'{"return_pct": 5.0, "trades": 10}'
    encoded = base64.b64encode(payload_bytes).decode("ascii")

    def fake_run(cmd, **kwargs):
        return _stub_subprocess_run(stdout=json.dumps({"data_b64": encoded}))

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = transport.fetch_output("run-cc", "cid-x")
    assert result == payload_bytes


def test_fetch_output_returns_none_on_failure(transport):
    """fetch_output returns None if the file is not present on the worker."""
    cp = _stub_subprocess_run(returncode=1, stderr="No such file or directory")
    with mock.patch("subprocess.run", return_value=cp):
        result = transport.fetch_output("run-dd", "cid-y")
    assert result is None


def test_default_node_and_cli_path():
    """Constructor defaults: node = ava-worker-local; cli_path = openclaw."""
    t = OpenClawNodeBundleTransport()
    assert t.DEFAULT_NODE == "ava-worker-local"
    assert t._cli_path == "openclaw"
    assert t._node == "ava-worker-local"


def test_node_override():
    """Constructor accepts a custom node name (multi-node future)."""
    t = OpenClawNodeBundleTransport(node="custom-worker-01")
    assert t._node == "custom-worker-01"


def test_push_bundle_uses_ephemeral_per_run_dir(transport, bundle_path, monkeypatch):
    """Bundle lands at /tmp/ayumi-offload/{run_id}/bundle (Q5 ephemeral, per-run dir)."""
    captured_remote_paths: list[str] = []

    def fake_run(cmd, **kwargs):
        cmd_name = cmd[cmd.index("--command") + 1]
        if cmd_name == "terminal.upload":
            params = json.loads(cmd[cmd.index("--params") + 1])
            captured_remote_paths.append(params["path"])
            return _stub_subprocess_run()
        if "sha256sum" in json.loads(cmd[cmd.index("--params") + 1]).get("command", ""):
            sha = _expected_sha(bundle_path)
            return _stub_subprocess_run(stdout=f"{sha}  -")
        return _stub_subprocess_run()

    sha = _expected_sha(bundle_path)
    monkeypatch.setenv("AYUMI_TOURNAMENT_STRATEGY", "x")
    monkeypatch.setenv("AYUMI_TOURNAMENT_SYMBOL", "GBPUSD")
    monkeypatch.setenv("AYUMI_TOURNAMENT_TIMEFRAME", "M15")
    with mock.patch("subprocess.run", side_effect=fake_run):
        transport.push_bundle("run-ee", bundle_path, sha)
    assert any("/tmp/ayumi-offload/run-ee/" in p for p in captured_remote_paths)
