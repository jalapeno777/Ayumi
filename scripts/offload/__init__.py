"""Ayumi node-offload runner v1 — thin wrapper over OpenClaw node transport.

Dispatches backtest/tournament matrix cells to ava-worker-local (8c / 39GB
RAM / WSL2 kernel; RTX 5060 Ti present but NOT wired in v1 — documented
extension point only, deferred until ML 1C.4 or MC bootstrap profiling).

Council-locked design (2026-09-15, Kaito+Sora consensus, 3 reviews):
- CPU-first v1; no CUDA/RAPIDS deps.
- Thin transport — wrap existing OpenClaw node transport (system.run +
  file transfer). No Docker, no daemon, no parallel SSH/rsync auth stack.
- 53GB DuckDB does NOT ship per run. Worker is read-only on the DB.
- Per-cell JSON manifests with git_sha + env_lock_hash; push-bundle model;
  --resume skips verified cells; loud version-skew rejection.
- Local fallback is for resilience, not equivalence — observability only.

Non-goals (mirrored from card AC + Tomoe brief §5):
- GPU wiring; fault-injection (Riko card 27dea9ee); matrix content
  (Tsubaki card 05fa0065); modifications to live ayumi-forward-test.

Public surface (cycle 1): seed.py, transport.py, manifest.py.
CLI dispatch loop (run_matrix_remote.py) lands in cycle 2.
"""

from __future__ import annotations

__version__ = "0.1.0-v1-skeleton"
