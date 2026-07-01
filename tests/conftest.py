"""Tests conftest — standard fixtures and path setup.

(BQ-1037: previous version used invalid pytest_collection_start /
pytest_collection_finish hooks which caused INTERNALERROR. Those have
been removed. Module-level sys.modules pollution is handled per-test
via monkeypatch fixtures in the individual test files.)
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from _project_root import PROJECT_ROOT


# Autouse: ensure RiskGuard default state file doesn't leak between tests.
@pytest.fixture(autouse=True)
def _isolate_risk_guard_state(monkeypatch, tmp_path):
    """Redirect RiskGuard's default state_path to a temp dir so tests
    don't pick up production state or pollute each other."""
    fake_state = str(tmp_path / "risk_guard_state.json")
    # Patch the default parameter value so any RiskGuard() created
    # without an explicit state_path uses the temp path.
    monkeypatch.setattr(
        "adapters.ctrader.risk_guard.RiskGuard.__init__.__defaults__",
        (None, 100000.0, fake_state),
    )
    yield


@pytest.fixture
def tmp_state_dir(tmp_path):
    d = tmp_path / "kill_switches"
    d.mkdir()
    return str(d)


@pytest.fixture
def mock_kill_switch(tmp_state_dir):
    from adapters.ctrader.kill_switch import KillSwitchManager
    mgr = KillSwitchManager(state_dir=tmp_state_dir)
    return mgr
