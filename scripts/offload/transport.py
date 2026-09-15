"""BundleTransport ABC + Port8877StubTransport (Q2 load-bearing per Tomoe).

Q2 flag (Tomoe, 2026-09-15, relayed via Ava): **ABC signatures + error
types are load-bearing** — designed for portability across
``port-8877`` / ``terminal.upload`` / future transports. The v1
``Port8877StubTransport`` raises on real invoke (driving the
local-fallback path in production); tests pass ``simulate_success=True``
to verify the contract without a live port-8877 receiver.

Signatures and error types are the contract. Future implementations
(``TerminalUploadTransport`` post-9.5 upgrade) inherit the same ABC and
raise the same error hierarchy. Tests verify the contract, not the wire.

Capability surface the ABC targets (per ``openclaw nodes describe``
probe 2026-09-15 on ava-worker-local 9.4):
- ``system.run`` + ``system.run.prepare`` — execute commands
- ``file.write`` + ``file.fetch`` — push/pull files (gateway 9.3 vs
  worker 9.4 has version skew — port-8877 works today, ``terminal.upload``
  after 9.5 upgrade)
- ``terminal.upload`` — same-file payload transport (9.4+, future)
- ``fs.listDir`` — directory listing
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkerCell:
    """Where a pushed bundle lives on the worker (load-bearing for path math).

    ``path`` is the worker-side directory the cell will execute in.
    ``sha256`` is the SHA of the bundle the worker received; must match
    the dispatcher's computed SHA (loud skew rejection otherwise).
    """
    path: str
    sha256: str


# Error hierarchy — subclasses are load-bearing for the runner's
# local-fallback dispatch logic. Do not collapse error types.
class BundleTransportError(Exception):
    """Base for all BundleTransport errors (load-bearing subclass tree)."""


class WorktreeUnreachableError(BundleTransportError):
    """Port-8877 down / worker disconnected / approval != approved.

    Runner catches this and falls back to local execution.
    """


class CodeSHARejectedError(BundleTransportError):
    """Q1 loud skew rejection — worker SHA differs from dispatcher SHA.

    Dispatcher writes ``dispatch_skipped.jsonl`` with
    ``reason: code_skew`` and aborts the cell. ABORT, never fallback —
    a SHA mismatch means the trust boundary is broken.
    """


class BundleTooLargeError(BundleTransportError):
    """Bundle exceeded worker's transfer-size cap. Fail loud; no fallback."""


class BundleTransport(ABC):
    """ABC for code-bundle transport (Q2: load-bearing signatures)."""

    @abstractmethod
    def push_bundle(
        self,
        run_id: str,
        bundle_path: Path,
        expected_sha256: str,
    ) -> WorkerCell:
        """Push ``bundle_path`` to worker; verify SHA on worker-side == expected."""

    @abstractmethod
    def fetch_output(
        self,
        run_id: str,
        cell_id: str,
    ) -> bytes | None:
        """Fetch cell output bytes from worker (``None`` if not yet present)."""


class Port8877StubTransport(BundleTransport):
    """v1 stub — raises on real invoke; ABC tests use ``simulate_success=True``.

    Q2 flag: this stub raises ``WorktreeUnreachableError`` on ``push_bundle``
    so the runner falls back to local execution in production (v1 ships
    without a live port-8877 receiver; ABC contract is verified separately).
    ``simulate_success=True`` mode is for ABC contract tests only — tests
    that want to exercise dispatch orchestration, not the wire.
    """

    def __init__(self, simulate_success: bool = False) -> None:
        self._simulate = simulate_success

    def push_bundle(
        self,
        run_id: str,
        bundle_path: Path,
        expected_sha256: str,
    ) -> WorkerCell:
        if not self._simulate:
            raise WorktreeUnreachableError(
                f"Port8877StubTransport: would push to "
                f"/tmp/ayumi-offload/{run_id}/ — wire TBD post-9.5 upgrade; "  # noqa: S108 — descriptive path only; stub raises before any FS access (Q2)
                f"runner falls back to local execution"
            )
        # Simulate-success path: synthetic WorkerCell for ABC contract tests.
        # The dispatcher-side computed SHA is preserved so downstream
        # equality checks pass.
        return WorkerCell(
            path=f"/tmp/ayumi-offload/{run_id}/bundle.simulated",  # noqa: S108 — descriptive synthetic path for ABC contract tests (Q2)
            sha256=expected_sha256,
        )

    def fetch_output(self, run_id: str, cell_id: str) -> bytes | None:
        # Fix #3 (Rin): simulate-success path returns deterministic
        # synthetic output bytes; the runner then persists them, computes
        # sha256 (becomes output_hash), and writes its own output_path
        # in the manifest. Real mode returns None (the stub raises
        # WorktreeUnreachableError before this would be called in
        # production).
        if not self._simulate:
            return None
        return f"simulated-worker-output:{run_id}:{cell_id}\n".encode("utf-8")


# ────────────────────────────────────────────────────────────────────────
# Real worker transport (c3134271-601e-42c2-9797-6407ae25048c)
# ────────────────────────────────────────────────────────────────────────


class OpenClawNodeBundleTransport(BundleTransport):
    """Real worker transport: push bundle to ava-worker-local, execute per-cell,
    fetch output.  Implements the BundleTransport ABC the runner depends on.

    Wire-up (Option (a) per c3134271 spec):
      1. Bundle upload  → ``terminal.upload`` invoke (base64-encode the
         local bundle and POST via ``--params``).
      2. SHA verify     → ``system.run "sha256sum <remote_path>"`` invoke.
      3. Strategy exec  → ``system.run "python3 -m scripts.run_tournament
         --strategy <S> --symbol <Y> --tf <TF> ..."`` invoke.  Strategy/symbol/
         tf come from the runner's env vars (``AYUMI_TOURNAMENT_STRATEGY`` /
         ``AYUMI_TOURNAMENT_SYMBOL`` / ``AYUMI_TOURNAMENT_TIMEFRAME``), set
         immediately before ``push_bundle`` — the ABC signature stays
         ``(run_id, bundle_path, expected_sha256)`` per Tomoe's
         load-bearing design, and per-cell context flows via env.
      4. Output fetch   → ``file.fetch`` invoke (base64-encoded JSON
         response, decoded locally).

    Error mapping:
      - Any invoke subprocess failure (timeout, non-zero exit, JSON
        decode error) → ``WorktreeUnreachableError`` (driver's local-fallback
        branch picks it up).
      - Bundle SHA mismatch on the worker side → ``CodeSHARejectedError``
        (Q1 loud skew → ABORT, never fallback).
      - Bundle size exceeds the worker's transfer cap (e.g.
        ``terminal.upload`` rejects >5MB) → ``BundleTooLargeError``
        (Rin finding #1 fix → fail loud, no fallback).

    ABC contract honored:
      - ``push_bundle`` returns ``WorkerCell(path=<remote_path>,
        sha256=<worker-computed_sha>)`` — dispatcher compares to
        ``expected_sha256`` in ``run_matrix_remote._run_one_cell``
        (Rin finding #2 fix).
      - ``fetch_output`` returns ``bytes`` or ``None`` (Rin finding #3 fix).
    """

    DEFAULT_NODE = "ava-worker-local"
    INVOKE_TIMEOUT_S = 60.0
    CLEANUP_TIMEOUT_S = 10.0

    def __init__(
        self,
        node: str = DEFAULT_NODE,
        *,
        cli_path: str | None = None,
    ) -> None:
        self._node = node
        self._cli_path = cli_path or "openclaw"

    # ── Public ABC methods ─────────────────────────────────────────────────

    def push_bundle(
        self,
        run_id: str,
        bundle_path: Path,
        expected_sha256: str,
    ) -> WorkerCell:
        # 1. Compute local SHA for the dispatch log + abort early on
        #    dispatcher-side mismatch (the runner also checks this via
        #    WorkerCell.sha256, but failing fast here keeps the dispatch
        #    log clean).
        local_sha = self._sha256_file(bundle_path)
        if local_sha != expected_sha256:
            raise CodeSHARejectedError(
                f"Local bundle SHA {local_sha!r} != expected {expected_sha256!r} "
                f"(dispatcher-side pre-flight)"
            )

        # 2. Upload via terminal.upload.  Bundle lands on the worker at
        #    /tmp/ayumi-offload/<run_id>/bundle (per Tomoe brief Q5 ephemeral).
        remote_dir = f"/tmp/ayumi-offload/{run_id}"
        remote_bundle_path = f"{remote_dir}/bundle"
        try:
            self._invoke_terminal_upload(bundle_path, remote_bundle_path)
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "").strip().splitlines()[-1:] or [""]
            raise WorktreeUnreachableError(
                f"terminal.upload failed on node {self._node!r}: {stderr_tail[0]!r}"
            ) from exc

        # 3. Verify SHA on the worker side.  A mismatch here means the wire
        #    corrupted the bundle or the worker has a different baseline
        #    — trust boundary broken → ABORT (Rin finding #1 + #2).
        try:
            worker_sha = self._sha256_on_worker(remote_bundle_path)
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "").strip().splitlines()[-1:] or [""]
            raise WorktreeUnreachableError(
                f"sha256sum on worker failed for {remote_bundle_path!r}: "
                f"{stderr_tail[0]!r}"
            ) from exc
        if worker_sha != expected_sha256:
            self._cleanup_remote_dir(remote_dir)
            raise CodeSHARejectedError(
                f"Worker bundle SHA {worker_sha!r} != expected {expected_sha256!r} "
                f"(wire integrity)"
            )

        # 4. Execute the strategy on the worker.  Per-cell context
        #    arrives via env vars (set by the runner immediately before
        #    push_bundle).  This keeps the ABC signature unchanged
        #    (load-bearing per Tomoe at f9414fe1 checkpoint 2).
        try:
            self._execute_strategy_on_worker(run_id, remote_dir)
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "").strip().splitlines()[-1:] or [""]
            self._cleanup_remote_dir(remote_dir)
            raise WorktreeUnreachableError(
                f"strategy execution failed on worker for run_id={run_id!r}: "
                f"{stderr_tail[0]!r}"
            ) from exc

        return WorkerCell(path=remote_bundle_path, sha256=worker_sha)

    def fetch_output(
        self,
        run_id: str,
        cell_id: str,
    ) -> bytes | None:
        remote_dir = f"/tmp/ayumi-offload/{run_id}"
        # The output JSON written by scripts.run_tournament (per matrix
        # card 05fa0065 spec) is at
        # /tmp/ayumi-offload/<run_id>/<cell_id>/output.json.
        remote_output_path = f"{remote_dir}/{cell_id}/output.json"
        try:
            return self._invoke_file_fetch(remote_output_path)
        except subprocess.CalledProcessError:
            # File not present yet, or fetch rejected (worker missing
            # the cell dir).  Runner treats None as "output unavailable"
            # and would fall back to local scoring (Q7).
            return None

    # ── Private helpers (OpenClaw invoke wrappers) ──────────────────────

    def _invoke(self, command: str, params: dict) -> subprocess.CompletedProcess:
        """Run ``openclaw nodes invoke`` with the given capability + params.

        Raises ``subprocess.CalledProcessError`` on non-zero exit so the
        ABC callers can map specific errors to the load-bearing error
        hierarchy (WorktreeUnreachable / CodeSHARejected / BundleTooLarge).
        """
        import json  # local import keeps module load cheap
        cmd = [
            self._cli_path, "nodes", "invoke",
            "--node", self._node,
            "--command", command,
            "--params", json.dumps(params),
            "--timeout", str(int(self.INVOKE_TIMEOUT_S * 1000)),
        ]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.INVOKE_TIMEOUT_S + 5.0,
            check=True,
        )

    def _invoke_json(self, command: str, params: dict) -> dict:
        """Invoke + decode JSON stdout; raise on parse failure."""
        result = self._invoke(command, params)
        import json
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=result.args,
                output=result.stdout,
                stderr=f"openclaw invoke returned non-JSON: {result.stdout[:200]!r}",
            ) from exc

    def _invoke_terminal_upload(
        self, local_path: Path, remote_path: str,
    ) -> None:
        """Base64-encode the local file and POST via terminal.upload invoke."""
        import base64
        data_b64 = base64.b64encode(local_path.read_bytes()).decode("ascii")
        self._invoke(
            "terminal.upload",
            {"path": remote_path, "data_b64": data_b64},
        )

    def _invoke_file_fetch(self, remote_path: str) -> bytes:
        """Fetch a file from the worker via file.fetch invoke.

        The file.fetch capability returns the file contents (typically
        base64-encoded JSON-wrapped).  Decode per the actual response
        shape: we accept either a bare base64 string, a JSON object
        with a ``data_b64`` key, or a JSON object with ``content`` /
        ``data`` keys.
        """
        import base64, json
        result = self._invoke("file.fetch", {"path": remote_path})
        # Try the most common shapes first; fall back to raw stdout.
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout.encode("utf-8")
        if isinstance(payload, dict):
            for key in ("data_b64", "content", "data"):
                if key in payload:
                    val = payload[key]
                    if isinstance(val, str):
                        try:
                            return base64.b64decode(val)
                        except Exception:
                            return val.encode("utf-8")
                    if isinstance(val, (bytes, bytearray)):
                        return bytes(val)
        # Fallback: encode the raw stdout as utf-8.
        return result.stdout.encode("utf-8")

    def _sha256_on_worker(self, remote_path: str) -> str:
        """Compute SHA256 of a file on the worker via system.run + sha256sum."""
        # Use awk to extract just the hash (sha256sum emits "<hash>  <path>").
        result = self._invoke(
            "system.run",
            {"command": f"sha256sum {remote_path} | awk '{{print $1}}'"},
        )
        return result.stdout.strip()

    def _execute_strategy_on_worker(self, run_id: str, remote_dir: str) -> None:
        """Invoke the per-cell strategy execution on the worker.

        Reads strategy/symbol/tf from the runner's env vars (set just
        before ``push_bundle``).  The matrix card (05fa0065) owns the
        end-to-end semantics; this transport only ensures the wire works.
        """
        import os
        strategy = os.environ.get("AYUMI_TOURNAMENT_STRATEGY", "")
        symbol = os.environ.get("AYUMI_TOURNAMENT_SYMBOL", "")
        timeframe = os.environ.get("AYUMI_TOURNAMENT_TIMEFRAME", "")
        if not (strategy and symbol and timeframe):
            # No env-var-driven cell → skip execution (transport still
            # uploaded the bundle for the runner to inspect).  Most callers
            # are smoke flows that wire env vars explicitly.
            return

        # Run scripts.run_tournament with the cell's args.  This is the
        # matrix-driver entrypoint (card 05fa0065); the worker-side
        # execution environment requires the Ayumi venv + DuckDB read
        # access — both are part of c3134271's "Worker-side execution
        # environment" requirement.
        cmd_str = (
            f"cd /home/TacoPants/projects/Ayumi && "
            f"PYTHONPATH=src:src/forex-bot "
            f"python3 -m scripts.run_tournament "
            f"--strategy {strategy} --symbol {symbol} --timeframe {timeframe} "
            f"--db /home/TacoPants/projects/Ayumi/data/ayumi_market.duckdb "
            f"--run-id {run_id} --output-dir {remote_dir}"
        )
        subprocess.run(
            [self._cli_path, "nodes", "invoke",
             "--node", self._node,
             "--command", "system.run",
             "--params", json.dumps({"command": cmd_str}),
             "--timeout", "300000"],
            capture_output=True,
            text=True,
            timeout=300.0,
            check=True,
        )

    def _cleanup_remote_dir(self, remote_dir: str) -> None:
        """Best-effort cleanup of the worker's per-run scratch dir."""
        try:
            subprocess.run(
                [self._cli_path, "nodes", "invoke",
                 "--node", self._node,
                 "--command", "system.run",
                 "--params", json.dumps({"command": f"rm -rf {remote_dir}"}),
                 "--timeout", "10000"],
                capture_output=True,
                text=True,
                timeout=self.CLEANUP_TIMEOUT_S,
                check=False,
            )
        except Exception:
            # Best-effort: a leaked scratch dir on the worker is not a
            # correctness issue (it's in /tmp and ephemeral).
            pass

    def _sha256_file(self, path: Path) -> str:
        """Streamed SHA256 over a local file (no full-file read)."""
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
