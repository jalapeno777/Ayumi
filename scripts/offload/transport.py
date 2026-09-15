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
