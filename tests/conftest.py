"""Tests conftest — standard fixtures and path setup.

(BQ-1037: previous version used invalid pytest_collection_start /
pytest_collection_finish hooks which caused INTERNALERROR. Those have
been removed. Module-level sys.modules pollution is handled per-test
via monkeypatch fixtures in the individual test files.)
"""

from pathlib import Path

import pytest

from _project_root import PROJECT_ROOT


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
