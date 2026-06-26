"""Tests for StatePersistence."""

import json
import os

import pytest
from risk.sl_position_sizer import SLPositionSizer
from risk.state_persistence import StatePersistence


@pytest.fixture
def sizer():
    return SLPositionSizer(account_balance=10000.0)


@pytest.fixture
def persistence(tmp_path):
    return StatePersistence(state_path=str(tmp_path / "risk_state.json"))


class TestStatePersistence:

    def test_save_restore_cycle(self, sizer, persistence):
        sizer._daily_risk_used = 50.0
        sizer._open_risk = 25.0
        sizer.breaker.record_trade(True)
        sizer.breaker.record_trade(False)

        persistence.save(sizer)

        new_sizer = SLPositionSizer(account_balance=5000.0)
        result = persistence.restore(new_sizer)

        assert result is True
        assert new_sizer.account_balance == 10000.0
        assert new_sizer._daily_risk_used == 50.0
        assert new_sizer._open_risk == 25.0
        assert len(new_sizer.breaker.recent_trades) == 2

    def test_restore_missing_file(self, sizer, persistence):
        result = persistence.restore(sizer)
        assert result is False

    def test_restore_corrupt_file(self, sizer, persistence, tmp_path):
        (tmp_path / "risk_state.json").write_text("BROKEN")
        result = persistence.restore(sizer)
        assert result is False

    def test_atomic_write_no_partial(self, sizer, persistence, tmp_path):
        persistence.save(sizer)
        path = tmp_path / "risk_state.json"
        data = json.loads(path.read_text())
        assert "account_balance" in data
        assert "circuit_breaker" in data

    def test_get_state_returns_dict(self, sizer, persistence):
        state = persistence.get_state(sizer)
        assert isinstance(state, dict)
        assert state["account_balance"] == 10000.0
        assert "circuit_breaker" in state

    def test_empty_sizer_state(self, persistence, tmp_path):
        sizer = SLPositionSizer(account_balance=1000.0)
        persistence.save(sizer)

        restored = SLPositionSizer(account_balance=1.0)
        persistence.restore(restored)
        assert restored.account_balance == 1000.0
        assert restored._daily_risk_used == 0.0
        assert restored.breaker.halted is False

    def test_circuit_breaker_state_persists(self, sizer, persistence):
        sizer.breaker.halt("test reason", duration_hours=2)
        persistence.save(sizer)

        new_sizer = SLPositionSizer(account_balance=10000.0)
        persistence.restore(new_sizer)
        assert new_sizer.breaker.halted is True
        assert new_sizer.breaker.halt_reason == "test reason"
        assert new_sizer.breaker.halted_until is not None
