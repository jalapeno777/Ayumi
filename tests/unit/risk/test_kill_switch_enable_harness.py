"""Card 09e99147: harness kill-switch enable behavior (production stays disabled).

Covers:
  1. KillSwitchManager(disabled=False) overrides the class default and
     activates globally on demand (regression for card 09e99147).
  2. Harness-style use: FTMOGuard wired to an explicitly-enabled kill
     switch raises on FREEZE breach (mirrors backtest_blend_harness.py
     flow where _ftmo_guard.update() halts the eval loop on freeze).
  3. KillSwitchManager(disabled=True) keeps the production launcher
     silent (regression guard: class default must remain True so we do
     not silently flip live semantics).
  4. Startup log fires once at __init__ with the loud ENABLED/DISABLED
     message — operators can never lose visibility into enforcement.

The fixture in test_kill_switch.py already flips class _disabled; this
file takes the more explicit constructor-override path that the harness
now uses.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from adapters.ctrader.kill_switch import KillSwitchManager
from risk.ftmo_guard import FTMOAction, FTMOGuard


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def enabled_state_dir(tmp_path):
    """Temp state dir for the enabled kill switch."""
    d = tmp_path / "kill_switch_enabled"
    d.mkdir()
    return str(d)


@pytest.fixture
def disabled_state_dir(tmp_path):
    """Temp state dir for the disabled kill switch."""
    d = tmp_path / "kill_switch_disabled"
    d.mkdir()
    return str(d)


@pytest.fixture
def enabled_ks(enabled_state_dir):
    """Kill switch explicitly enabled via constructor (harness path)."""
    return KillSwitchManager(state_dir=enabled_state_dir, disabled=False)


@pytest.fixture
def disabled_ks(disabled_state_dir):
    """Kill switch inherits class default (production launcher path)."""
    return KillSwitchManager(state_dir=disabled_state_dir)


@pytest.fixture(autouse=True)
def _restore_class_default():
    """Make sure the class default is True at start AND end of each test.

    The production default (Craig directive Jun 27) must not be silently
    flipped by a misbehaving test. Restore even on assertion failure.
    """
    original = KillSwitchManager._disabled
    KillSwitchManager._disabled = True
    yield
    KillSwitchManager._disabled = original


# ── 1. Constructor override semantics ────────────────────────────────────────


class TestConstructorOverride:
    def test_disabled_false_constructor_enables_kill_switch(self, enabled_ks):
        """disabled=False must produce an ENABLED kill switch instance."""
        assert enabled_ks.is_disabled is False
        assert enabled_ks.is_active() is False
        # Activations must NOT be suppressed
        enabled_ks.activate_global_freeze(reason="unit_test", triggered_by="tsubaki")
        assert enabled_ks.is_active() is True
        assert enabled_ks.is_globally_frozen() is True

    def test_disabled_true_constructor_suppresses_activations(self, disabled_ks):
        """disabled=True must suppress activations (production safety default)."""
        assert disabled_ks.is_disabled is True
        disabled_ks.activate_global_kill(reason="unit_test", triggered_by="tsubaki")
        # Activation must be a no-op
        assert disabled_ks.is_active() is False
        assert disabled_ks.is_globally_killed() is False

    def test_class_default_preserved_when_disabled_arg_none(self, disabled_state_dir):
        """disabled=None (production launcher style) must inherit the class default."""
        # Class default is True (fixture restored). New instance must inherit.
        assert KillSwitchManager._disabled is True
        ks = KillSwitchManager(state_dir=disabled_state_dir, disabled=None)
        assert ks.is_disabled is True
        # And no instance attribute was set on the new object — class attribute
        # lookup is what returns True.
        assert "_disabled" not in ks.__dict__


# ── 2. Harness-style halt-on-breach flow (acceptance criterion 1) ───────────


class TestHarnessHaltOnBreach:
    """Mirror the backtest_blend_harness.py eval loop pattern.

    In the harness: ``_ftmo_action = _ftmo_guard.update(balance, open_n);
    if _ftmo_action.value in ('freeze', 'kill'): engine._running = False;
    break``. We exercise that exact sequence with an explicitly-enabled
    kill switch and assert it triggers the FREEZE halt.
    """

    def test_ftmo_freeze_engages_enabled_kill_switch(self, enabled_ks):
        """FTMOGuard wired to enabled kill switch: FREEZE on daily-DD breach."""
        guard = FTMOGuard(
            kill_switch=enabled_ks,
            starting_balance=10_000.0,
            challenge_type="1-step",
            trailing_dd=True,
        )
        # 4% daily loss = $400 drop — above the 3% FTMO daily-DD limit
        action = guard.update(current_balance=9_600.0, open_positions=1)
        assert action == FTMOAction.FREEZE
        # Enabled kill switch must have actually engaged (not suppressed)
        assert enabled_ks.is_globally_frozen() is True
        assert enabled_ks.is_active() is True

    def test_harness_eval_loop_halts_on_freeze(self, enabled_ks):
        """Mirror the harness `if action in ('freeze','kill'): break` flow."""
        guard = FTMOGuard(
            kill_switch=enabled_ks,
            starting_balance=10_000.0,
        )
        engine_running = True
        bars_processed = 0
        for bar_idx in range(200):
            # Simulate a runaway losing streak: -2% per bar
            balance = 10_000.0 * (0.98 ** (bar_idx + 1))
            action = guard.update(current_balance=balance, open_positions=1)
            bars_processed += 1
            if action.value in ("freeze", "kill"):
                engine_running = False
                break

        # The loop must have halted with the kill switch actually engaged.
        assert engine_running is False
        assert enabled_ks.is_active() is True
        assert bars_processed < 200  # Not every bar was processed

    def test_disabled_kill_switch_lets_guard_compute_but_blocks_activation(
        self, disabled_ks
    ):
        """With class default disabled=True, FTMOGuard sees breach but ks stays quiet."""
        # FTMO guard sees the breach and chooses FREEZE/KILL action, but the
        # kill switch activation is suppressed — exactly the parent card 76046374
        # failure mode where the harness drained -$123,700 with no halt.
        guard = FTMOGuard(
            kill_switch=disabled_ks,
            starting_balance=10_000.0,
        )
        action = guard.update(current_balance=9_500.0, open_positions=1)
        # FTMO logic itself still flags the breach
        assert action in (FTMOAction.FREEZE, FTMOAction.KILL)
        # But the kill switch was never actually engaged (suppressed)
        assert disabled_ks.is_active() is False


# ── 3. Startup log line is loud and informative ──────────────────────────────


class TestStartupLog:
    def test_disabled_startup_logs_administrative_disabled(self, disabled_state_dir, caplog):
        """disabled path: WARNING log states 'ADMINISTRATIVELY DISABLED'."""
        ks = KillSwitchManager(state_dir=disabled_state_dir)
        with caplog.at_level(logging.WARNING, logger="ayumi.ctrader.kill_switch"):
            # Already logged at __init__; re-trigger by calling __init__ again
            ks.__init__(state_dir=disabled_state_dir)
        # At least one record mentions ADMINISTRATIVELY DISABLED
        msgs = [r.getMessage() for r in caplog.records]
        assert any("ADMINISTRATIVELY DISABLED" in m for m in msgs), msgs

    def test_enabled_startup_logs_enforced(self, enabled_state_dir, caplog):
        """disabled=False path: WARNING log states 'ENABLED'."""
        ks = KillSwitchManager(state_dir=enabled_state_dir, disabled=False)
        with caplog.at_level(logging.WARNING, logger="ayumi.ctrader.kill_switch"):
            ks.__init__(state_dir=enabled_state_dir, disabled=False)
        msgs = [r.getMessage() for r in caplog.records]
        assert any("ENABLED" in m and "ADMINISTRATIVELY DISABLED" not in m for m in msgs), msgs


# ── 4. Mock-pattern compatibility with existing ftmo_guard tests ────────────


class TestMockPatternCompat:
    """The existing tests in test_ftmo_guard.py use MagicMock kill_switch
    objects and set ``ks.is_disabled = False`` to simulate an enabled
    switch. Verify that pattern still works after this change so we don't
    break the existing 28 ftmo_guard tests."""

    def test_mock_with_is_disabled_false_engages(self):
        ks = MagicMock()
        ks.is_active.return_value = False
        ks.is_disabled = False
        ks.is_globally_frozen.return_value = True  # pretend activation worked

        guard = FTMOGuard(kill_switch=ks, starting_balance=10_000.0)
        action = guard.update(current_balance=9_500.0, open_positions=1)
        ks.activate_global_freeze.assert_called_once()
        assert action == FTMOAction.FREEZE
