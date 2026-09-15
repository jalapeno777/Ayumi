"""Shared fixtures for the offload-runner test surface.

Pytest auto-discovers this ``conftest.py`` for the ``tests/offload/``
package. The repo-root ``tests/conftest.py`` autouse
``_guard_repo_data_writes`` fixture also applies — it fails any test
that writes under ``<repo>/data/``, forcing ``tmp_path`` use.
"""

from __future__ import annotations

import pathlib
import sys

# Make ``scripts/`` importable as ``offload.*`` for pytest collection.
# MUST run before any test module's import — conftest is loaded first.
_PKG_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_SCRIPTS_DIR = _PKG_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pytest

# v1 smoke matrix — same constants as
# ``scripts/offload/run_matrix_remote.SMOKE_MATRIX``.
SMOKE_MATRIX: list[tuple[str, str, str]] = [
    ("q1_mw_formation", "GBPUSD", "M5"),
    ("q1_mw_formation", "GBPUSD", "M15"),
]


@pytest.fixture
def smoke_cells() -> list[tuple[str, str, str]]:
    """The 2-cell smoke matrix used in the v1 card verification command."""
    return list(SMOKE_MATRIX)


@pytest.fixture
def output_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """Per-test dispatcher-side output root (mirrors ``run_matrix_remote``).

    Pass to ``run_matrix_remote.main()`` via ``--output-root <path>``.
    Production runs use ``<repo>/data/offload/<run-id>/`` by default; tests
    use ``tmp_path`` to satisfy the repo-root ``data/`` guard.
    """
    return tmp_path / "offload-out"
