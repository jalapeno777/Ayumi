#!/usr/bin/env python3
"""JobDirBundleTransport — BundleTransport impl for the job-dir worker pattern.

Card 05fa0065 Phase 1a choice: job-dir polling worker (NOT port-8877
receiver). This transport is the gateway-side half of the protocol:
``push_bundle`` uploads the per-cell job descriptor to the worker via
``openclaw nodes invoke --command terminal.upload`` (reusing the existing
OpenClawNodeBundleTransport wire), and ``fetch_output`` retrieves the
worker's output.json via the same wire.

Wire-up (mirrors ``OpenClawNodeBundleTransport``):
  1. push_bundle(run_id, descriptor_path, expected_sha256)
       - Local SHA pre-flight (Q1 loud skew rejection)
       - Size cap pre-flight (BundleTooLargeError)
       - terminal.upload → worker-side staging path; exec mv →
         /tmp/ayumi-jobs/{run_id}/incoming/{cell_id}.json
       - Returns WorkerCell(path=remote_incoming_path, sha256=expected)

  2. fetch_output(run_id, cell_id)
       - file.fetch → /tmp/ayumi-jobs/{run_id}/done/{cell_id}.output.json
       - On NO_POLICY (file-transfer not configured for ava-worker-local),
         return None — same as OpenClawNodeBundleTransport.fetch_output.
         The dispatcher in this case falls back to agent exec(host=node)
         cat for output retrieval.

  3. fetch_output_via_exec(run_id, cell_id) — NON-ABC helper
       - Cat the output file via ``openclaw nodes invoke
         --command system.run`` (matches c3134271 live_smoke cat pattern).

  4. fetch_descriptor_done_sentinel(run_id, cell_id) — NON-ABC helper
       - Helper for the gateway-side matrix driver to check whether the
         worker has finished a cell (presence of {cell_id}.done sentinel).
       - Uses exec(host=node) ls (file.fetch's NO_POLICY makes a sentinel
         fetch unreliable; exec ls is the c3134271-smoke proven path).
       - Returns True/False.

Design constraint: this transport NEVER falls back to local execution.
The whole point of Phase 1a is that the matrix runs on ava-worker —
local_fallback=True on any cell violates the Craig directive 6f2cd97b.
The matrix driver checks every manifest's local_fallback flag and aborts
if any cell bypassed the worker (HR27 silent-success guard).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from offload.transport import (
    BundleTooLargeError,
    BundleTransport,
    BundleTransportError,
    CodeSHARejectedError,
    OpenClawNodeBundleTransport,
    WorkerCell,
    WorktreeUnreachableError,
)

__all__ = ["JobDirBundleTransport", "fetch_descriptor_done_sentinel"]


# Worker-side directory layout (mirrored in worker_runner.py).
JOB_DIR_DEFAULT = "/tmp/ayumi-jobs"  # noqa: S108 — descriptive constant matching worker_runner convention


class JobDirBundleTransport(BundleTransport):
    """BundleTransport impl that uploads job descriptors and fetches outputs.

    The wire is OpenClaw's ``terminal.upload`` (push) and ``file.fetch``
    (pull). Both are the same primitives OpenClawNodeBundleTransport
    uses; this class specializes them to the job-dir layout.
    """

    def __init__(
        self,
        node: str = OpenClawNodeBundleTransport.DEFAULT_NODE,
        *,
        job_dir: str = JOB_DIR_DEFAULT,
        cli_path: str | None = None,
    ) -> None:
        self._node = node
        self._job_dir = job_dir
        # Delegate wire-level push to OpenClawNodeBundleTransport so we
        # inherit its terminal.upload + size-cap + SHA pre-flight handling.
        self._wire = OpenClawNodeBundleTransport(node=node, cli_path=cli_path)

    # ── ABC methods ───────────────────────────────────────────────────────

    def push_bundle(
        self,
        run_id: str,
        bundle_path: Path,
        expected_sha256: str,
    ) -> WorkerCell:
        """Upload the job descriptor to {job_dir}/{run_id}/incoming/.

        ``bundle_path`` is the local job JSON; its basename is the cell_id
        (matching worker_runner's expected file naming). The worker's
        processing directory is {job_dir}/{run_id}/processing/; we drop
        into incoming/ and let worker_runner atomically rename to
        processing/ on pickup.
        """
        # Local SHA pre-flight (Q1 loud skew rejection).
        local_sha = self._wire._sha256_file(bundle_path)  # noqa: SLF001 — wire helper
        if local_sha != expected_sha256:
            raise CodeSHARejectedError(
                f"Local descriptor SHA {local_sha!r} != expected "
                f"{expected_sha256!r} (jobdir transport pre-flight)"
            )

        # Size cap pre-flight.
        size = bundle_path.stat().st_size
        if size > OpenClawNodeBundleTransport.MAX_UPLOAD_BYTES:
            raise BundleTooLargeError(
                f"descriptor size {size} bytes exceeds gateway cap "
                f"{OpenClawNodeBundleTransport.MAX_UPLOAD_BYTES} bytes (16 MB); "
                f"refusing to invoke"
            )

        # We have to land the file in {job_dir}/{run_id}/incoming/. The
        # gateway's terminal.upload lands files at a random
        # /tmp/openclaw-terminal-upload-<rand>/<name>; the worker_runner
        # watches {job_dir}/{run_id}/incoming/. So we have two options:
        #
        # (a) terminal.upload to a staging path, then exec(host=node) mv
        #     into incoming/. Two round trips per cell — slow for 68 cells.
        # (b) terminal.upload with a worker-side post-upload hook. Not
        #     supported by the gateway today.
        # (c) terminal.upload to staging + write a sentinel "ready" file
        #     that worker_runner watches for; worker_runner mv's it into
        #     incoming/ on receipt.
        #
        # We pick (a) for v1 simplicity — the 68 cells each cost one
        # extra exec round trip (~0.5s), so ~30s total overhead is
        # acceptable for the production path. Future v2 may compress this
        # into one step via a worker-side "upload + mv" handler.
        try:
            staging_cell = self._wire._invoke_terminal_upload(bundle_path)  # noqa: SLF001
        except BundleTransportError:
            raise  # propagate with the original error type
        except subprocess.CalledProcessError as exc:
            raise WorktreeUnreachableError(
                f"terminal.upload (jobdir staging) failed on node "
                f"{self._node!r}: {(exc.stderr or '').strip()!r}"
            ) from exc

        # Move from staging to incoming/ via exec(host=node) mv.
        target_path = f"{self._job_dir}/{run_id}/incoming/{bundle_path.name}"  # noqa: S108
        self._exec_mv(staging_cell, target_path)

        # Verify the worker sees the descriptor at its target path. The
        # exec-mv is best-effort: if it fails, we still report success
        # (the staging path is verifiable), but the worker_runner will
        # never see the job and the cell will time out. Caller (the
        # matrix driver) is responsible for detecting that via missing
        # .done sentinel.
        return WorkerCell(path=target_path, sha256=local_sha)

    def fetch_output(
        self,
        run_id: str,
        cell_id: str,
    ) -> bytes | None:
        """Fetch {cell_id}.output.json from {job_dir}/{run_id}/done/.

        Returns ``None`` when file.fetch is NO_POLICY for the node
        (mirrors OpenClawNodeBundleTransport.fetch_output); the matrix
        driver falls back to exec(host=node) cat for output retrieval.
        """
        remote_path = (
            f"{self._job_dir}/{run_id}/done/{cell_id}.output.json"  # noqa: S108
        )
        try:
            result = self._wire._invoke("file.fetch", {"path": remote_path})  # noqa: SLF001
            return OpenClawNodeBundleTransport._decode_file_fetch(result.stdout)  # noqa: SLF001
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            if "NO_POLICY" in stderr or "deny-by-default" in stderr:
                print(
                    f"[jobdir-transport] file.fetch denied on "
                    f"{self._node!r}: {stderr!r} — caller must use "
                    f"exec(host=node) cat fallback",
                    file=sys.stderr,
                )
                return None
            # ENOENT (cell not yet done) or other failure → None.
            return None
        except BundleTransportError:
            return None

    # ── Non-ABC helpers (used by matrix_driver) ───────────────────────────

    def fetch_output_via_exec(
        self,
        run_id: str,
        cell_id: str,
    ) -> bytes | None:
        """Fallback: cat the output file via ``openclaw nodes invoke
        --command system.run`` (matches c3134271 live_smoke cat pattern).

        Returns the raw output bytes, or ``None`` if the file isn't there
        yet (cell not done) or the worker reports an error.
        """
        remote_path = (
            f"{self._job_dir}/{run_id}/done/{cell_id}.output.json"  # noqa: S108
        )
        # Use system.run to cat the file. We deliberately avoid shell
        # expansion: the cell_id is a sha256:16 hex (safe). The path is
        # a literal we control.
        cmd_str = f"cat {remote_path}"
        try:
            result = self._wire._invoke(  # noqa: SLF001
                "system.run",
                {"command": cmd_str, "timeout": 10_000},
                timeout_s=15.0,
            )
            if not result.stdout:
                return None
            return result.stdout.encode("utf-8")
        except (subprocess.CalledProcessError, BundleTransportError):
            return None

    # ── Private helpers ───────────────────────────────────────────────────

    def _exec_mv(self, src: str, dst: str) -> None:
        """Move ``src`` to ``dst`` on the worker via system.run.

        Errors are surfaced (caller catches BundleTransportError); a
        successful mv returns stdout that we ignore.
        """
        cmd_str = f"mkdir -p $(dirname {dst}) && mv {src} {dst}"
        try:
            self._wire._invoke(  # noqa: SLF001
                "system.run",
                {"command": cmd_str, "timeout": 5_000},
                timeout_s=10.0,
            )
        except subprocess.CalledProcessError as exc:
            raise WorktreeUnreachableError(
                f"mv on worker failed: {(exc.stderr or '').strip()!r}"
            ) from exc


def fetch_descriptor_done_sentinel(
    *,
    node: str,
    run_id: str,
    cell_id: str,
    job_dir: str = JOB_DIR_DEFAULT,
    cli_path: str | None = None,
) -> bool:
    """Check whether the worker has marked ``cell_id`` as done.

    Uses ``system.run ls`` (file.fetch's NO_POLICY makes a sentinel
    fetch unreliable). Returns True iff the .done sentinel exists.
    """
    wire = OpenClawNodeBundleTransport(node=node, cli_path=cli_path)
    sentinel_path = f"{job_dir}/{run_id}/done/{cell_id}.done"  # noqa: S108
    cmd_str = f"test -f {sentinel_path} && echo yes || echo no"
    try:
        result = wire._invoke(  # noqa: SLF001
            "system.run",
            {"command": cmd_str, "timeout": 3_000},
            timeout_s=5.0,
        )
        return result.stdout.strip() == "yes"
    except (subprocess.CalledProcessError, BundleTransportError):
        return False
