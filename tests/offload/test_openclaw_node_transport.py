"""Unit tests for ``OpenClawNodeBundleTransport`` (c3134271).

Verifies the BundleTransport ABC contract via mocked CLI invocations.
The live-wire smoke (card AC #2) is the one pytest marked ``@live``
that runs against the real ``ava-worker-local`` node — gated on the
``AYUMI_RUN_LIVE_NODE_TESTS`` env var so unit CI doesn't trip the
node.

Coverage:
  - SHA256 pre-flight on the dispatcher side (Rin finding #2 wire integrity)
  - terminal.upload invoke with the gateway-validated param shape
    (name + contentBase64; source: ``daemon-BbqI59vQ.js:2744``)
  - Local size-cap pre-flight → fail-loud no fallback (Rin finding #1)
  - Gateway size-cap rejection (stderr pattern) → BundleTooLargeError
  - fetch_output decode variants (data_b64 / content / data / raw)
  - fetch_output NO_POLICY graceful-degradation (returns None + stderr log)
  - fetch_output other failure → None (ENOENT, exit-1)
  - Constructor defaults + node override
  - WorkerCell.path round-trip (real gateway returns path in payload)

DELEG-REF: c3134271-601e-42c2-9797-6407ae25048c
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
from contextlib import redirect_stderr
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


def _stub_cp(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    """Build a CompletedProcess-like mock for subprocess.run."""
    cp = subprocess.CompletedProcess(args=[], returncode=returncode)
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


def _gateway_terminal_upload_response(landing_path: str, size: int) -> str:
    """Real-shape JSON response the gateway emits on terminal.upload ok."""
    return json.dumps(
        {
            "ok": True,
            "nodeId": "9f86ae2ee063ab0ebb5a8daec9984988820840803317a1cbc761dc457f400186",
            "command": "terminal.upload",
            "payload": {"path": landing_path, "size": size},
        }
    )


@pytest.fixture()
def transport() -> OpenClawNodeBundleTransport:
    return OpenClawNodeBundleTransport(node="ava-worker-local")


@pytest.fixture()
def bundle_path(tmp_path: Path) -> Path:
    """Write a small test bundle (a single file) and return its FILE path.

    The transport's ``push_bundle`` treats ``bundle_path`` as a file
    (reads its bytes for terminal.upload), so the fixture must be a
    file, not a directory.
    """
    f = tmp_path / "bundle.py"
    f.write_bytes(b"print('hello from worker bundle')\n")
    return f


def _expected_sha(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _param_dict(cmd: list[str]) -> dict:
    """Extract the JSON ``--params`` payload from a mocked invoke call."""
    return json.loads(cmd[cmd.index("--params") + 1])


def _cmd_name(cmd: list[str]) -> str:
    return cmd[cmd.index("--command") + 1]


# ── push_bundle tests ──────────────────────────────────────────────────────


def test_push_bundle_uploads_with_name_and_contentBase64(
    transport,
    bundle_path,
):
    """Happy path: SHA pre-flight + terminal.upload with name+contentBase64.

    Verifies the wire-shape fix from commit 964342e1 (which passed
    ``data_b64`` instead of ``contentBase64`` and ``path`` instead of
    ``name`` — the gateway rejected both shapes silently).
    """
    sha = _expected_sha(bundle_path)
    captured_params: list[dict] = []

    def fake_run(cmd, **kwargs):
        params = _param_dict(cmd)
        captured_params.append(params)
        # Worker-side SHA verify is OUT of scope from the runner
        # subprocess (system.run is reserved-for-shell).  Only
        # terminal.upload is invoked.
        return _stub_cp(
            stdout=_gateway_terminal_upload_response(
                "/tmp/openclaw-terminal-upload-abc123/bundle.py",  # noqa: S108 — descriptive test fixture path; not a FS op
                size=bundle_path.stat().st_size,
            )
        )

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = transport.push_bundle("run-x", bundle_path, sha)

    assert isinstance(result.sha256, str) and len(result.sha256) == 64
    assert result.sha256 == sha  # dispatcher-side SHA preserved
    assert result.path == "/tmp/openclaw-terminal-upload-abc123/bundle.py"  # noqa: S108 — same fixture path as above
    assert len(captured_params) == 1
    params = captured_params[0]
    # Exact wire-shape: name + contentBase64 (gateway source: daemon-BbqI59vQ.js:2744)
    assert "name" in params and "contentBase64" in params
    assert "data_b64" not in params
    assert "path" not in params  # legacy data_b64/path shape must not reappear
    assert params["name"] == bundle_path.name
    # Base64 decodes back to the original bundle bytes.
    assert base64.b64decode(params["contentBase64"]) == bundle_path.read_bytes()


def test_push_bundle_local_preflight_sha_mismatch_raises_codesharejected(
    transport,
    bundle_path,
):
    """Local bundle SHA != expected → CodeSHARejectedError BEFORE any wire call."""
    sha = _expected_sha(bundle_path)
    with mock.patch("subprocess.run") as m:
        with pytest.raises(CodeSHARejectedError) as excinfo:
            transport.push_bundle("run-y", bundle_path, "0" * 64)
    assert sha in str(excinfo.value)
    assert "pre-flight" in str(excinfo.value)
    # Critical: subprocess.run was NEVER called (pre-flight fails fast).
    assert m.call_count == 0


def test_push_bundle_local_size_cap_raises_bundle_too_large(transport, tmp_path):
    """Local size-cap pre-flight → BundleTooLargeError BEFORE any wire call.

    Off-routing the gateway wire when a bundle would obviously exceed
    the 16 MB terminal.upload cap gives the dispatcher a clear fail-
    loud signal (Rin finding #1), not a confused WorktreeUnreachable.
    """
    big = tmp_path / "too-big.py"
    # Allocate slightly over the 16 MB cap.
    big.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    sha = _expected_sha(big)

    with mock.patch("subprocess.run") as m:
        with pytest.raises(BundleTooLargeError) as excinfo:
            transport.push_bundle("run-z", big, sha)

    assert "exceeds gateway cap" in str(excinfo.value)
    assert "16 MB" in str(excinfo.value)
    assert m.call_count == 0


def test_push_bundle_terminal_upload_failure_raises_worktree(transport, bundle_path):
    """terminal.upload subprocess failure → WorktreeUnreachableError."""
    sha = _expected_sha(bundle_path)
    cp = _stub_cp(returncode=1, stderr="connection refused by node")
    with mock.patch("subprocess.run", return_value=cp):
        with pytest.raises(WorktreeUnreachableError) as excinfo:
            transport.push_bundle("run-aa", bundle_path, sha)
    assert "connection refused" in str(excinfo.value)


def test_push_bundle_gateway_size_cap_raises_bundle_too_large(
    transport,
    bundle_path,
):
    """Gateway-side size-cap rejection (stderr pattern) → BundleTooLargeError.

    Per gateway source ``terminal-file-upload-rFs_tRIM.js:37`` the error
    message is "terminal upload exceeds <N> bytes".  The transport
    detects this pattern and routes through BundleTooLargeError so the
    runner fails loud + no fallback (Rin finding #1).
    """
    sha = _expected_sha(bundle_path)
    cp = _stub_cp(returncode=2, stderr="terminal upload exceeds 16777216 bytes")
    with mock.patch("subprocess.run", return_value=cp):
        with pytest.raises(BundleTooLargeError) as excinfo:
            transport.push_bundle("run-bb", bundle_path, sha)
    assert "terminal.upload rejected bundle" in str(excinfo.value)


def test_push_bundle_empty_file_raises_bundle_too_large(transport, tmp_path):
    """Refusing to upload an empty file is also a fail-loud bundle-too-large signal."""
    empty = tmp_path / "empty.py"
    empty.write_bytes(b"")
    sha = _expected_sha(empty)
    with mock.patch("subprocess.run") as m:
        with pytest.raises(BundleTooLargeError) as excinfo:
            transport.push_bundle("run-cc", empty, sha)
    assert "empty file" in str(excinfo.value).lower()
    assert m.call_count == 0


# ── fetch_output tests ─────────────────────────────────────────────────────


def test_fetch_output_returns_decoded_bytes_data_b64(transport):
    """file.fetch returns base64-wrapped JSON → decoded bytes."""
    payload_bytes = b'{"return_pct": 5.0, "trades": 10}'
    encoded = base64.b64encode(payload_bytes).decode("ascii")

    def fake_run(cmd, **kwargs):
        return _stub_cp(stdout=json.dumps({"data_b64": encoded}))

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = transport.fetch_output("run-dd", "cid-x")
    assert result == payload_bytes


def test_fetch_output_returns_decoded_bytes_content_key(transport):
    """file.fetch may wrap content under ``content`` key (alternate shape)."""
    payload_bytes = b'{"metrics": {"n_trades": 50}}'
    encoded = base64.b64encode(payload_bytes).decode("ascii")

    def fake_run(cmd, **kwargs):
        return _stub_cp(stdout=json.dumps({"content": encoded}))

    with mock.patch("subprocess.run", side_effect=fake_run):
        result = transport.fetch_output("run-ee", "cid-y")
    assert result == payload_bytes


def test_fetch_output_no_policy_returns_none_with_stderr_log(transport):
    """file.fetch NO_POLICY (file-transfer deny-by-default) → None + stderr warn.

    This is the EXPECTED behavior on ava-worker-local 2026-09-15 (no
    file-transfer plugin node-allow).  Live smoke captures output via
    the agent's exec(host=node) cat path; the transport surfaces the
    structured warning so the runner can adopt the agent-driven
    workflow.
    """
    cp = _stub_cp(
        returncode=1,
        stderr=(
            "file.fetch NO_POLICY: no plugins.entries.file-transfer.config.nodes "
            "config; file-transfer is deny-by-default until configured"
        ),
    )
    captured_err = io.StringIO()
    with mock.patch("subprocess.run", return_value=cp):
        with redirect_stderr(captured_err):
            result = transport.fetch_output("run-ff", "cid-z")
    assert result is None
    err = captured_err.getvalue()
    assert "file.fetch denied" in err
    assert "NO_POLICY" in err or "deny-by-default" in err


def test_fetch_output_returns_none_on_enoent(transport):
    """file.fetch with ENOENT (cell output not yet present) → None (no log)."""
    cp = _stub_cp(returncode=1, stderr="No such file or directory")
    with mock.patch("subprocess.run", return_value=cp):
        result = transport.fetch_output("run-gg", "cid-q")
    assert result is None


def test_fetch_output_returns_raw_utf8_when_not_json(transport):
    """file.fetch sometimes returns raw bytes (non-JSON) → utf-8 fallback."""
    raw = "raw output text from worker"
    with mock.patch("subprocess.run", return_value=_stub_cp(stdout=raw)):
        result = transport.fetch_output("run-hh", "cid-r")
    assert result == raw.encode("utf-8")


# ── Constructor / config tests ─────────────────────────────────────────────


def test_default_node_and_cli_path():
    """Constructor defaults: node = ava-worker-local; cli_path = 'openclaw'."""
    t = OpenClawNodeBundleTransport()
    assert t.DEFAULT_NODE == "ava-worker-local"
    assert t._cli_path == "openclaw"
    assert t._node == "ava-worker-local"


def test_node_override():
    """Constructor accepts a custom node name (multi-node future)."""
    t = OpenClawNodeBundleTransport(node="custom-worker-01")
    assert t._node == "custom-worker-01"


def test_max_upload_bytes_constant_matches_gateway_source():
    """MAX_UPLOAD_BYTES must mirror gateway terminal-constants (16 MB)."""
    t = OpenClawNodeBundleTransport()
    # Source: terminal-constants-Bjk8k2kn.js (MAX_TERMINAL_UPLOAD_BYTES)
    assert t.MAX_UPLOAD_BYTES == 16 * 1024 * 1024


# ── Live-wire smoke test (gated on env var) ────────────────────────────────


LIVE_GATE_ENV = "AYUMI_RUN_LIVE_NODE_TESTS"


@pytest.mark.live
def test_live_push_bundle_uploads_to_ava_worker(transport, bundle_path):
    """LIVE: terminal.upload round-trip against the real ava-worker-local.

    Gated on AYUMI_RUN_LIVE_NODE_TESTS=1 so unit CI skips it.  Acquires
    a real claim on the worker, posts the bundle, returns the worker
    path.  Validates the gateway config is wired correctly so the
    transport is production-ready (see c3134271 card AC #2 — extends
    proof beyond unit tests).

    This test pre-dates --transport=node defaulting; it deliberately
    does NOT exercise fetch_output (file.fetch is NO_POLICY today;
    live smoke for fetch_output is the agent's exec(host=node) cat
    path documented in transport.py module docstring).
    """
    if os.environ.get(LIVE_GATE_ENV) != "1":
        pytest.skip(f"set {LIVE_GATE_ENV}=1 to enable live node tests (requires paired ava-worker-local node)")

    sha = _expected_sha(bundle_path)
    result = transport.push_bundle("live-smoke-pytest", bundle_path, sha)

    # WorkerCell.path returned by the gateway points into the per-call
    # random /tmp/ subdir created by terminal.upload.
    assert result.path.startswith(transport.UPLOAD_RAND_DIR_PREFIX)
    assert result.path.endswith(bundle_path.name)
    assert result.sha256 == sha
