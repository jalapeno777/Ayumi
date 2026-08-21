"""Tests for TestCanaryStrategy disable behavior (Phase 1A).

Verifies that:
- tp_sl_pct=0.0 → disabled (enabled=False, evaluate()=None)
- tp_sl_pct>0 → enabled with WARNING log
- Env var gating works correctly
"""

from __future__ import annotations

import logging
import os
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clean_backtest_stub():
    """Remove _tsukasa_stub pollution from sys.modules before each test.

    test_forward_test_flag_persistence.py installs fake backtest.* modules
    at import (collection) time without cleanup. The polluter sets
    ``_tsukasa_stub = True`` on the ``backtest`` package but NOT on
    sub-modules created via ``_make()`` (``backtest.engine``,
    ``backtest.types``, etc.), so checking the marker alone misses them.

    When the parent ``backtest`` package is a stub we remove **all**
    ``backtest.*`` entries so Python re-imports the real modules during
    our tests.  Stubs are restored afterward so the polluter's tests
    still work.
    """
    saved = {}
    bt_pkg = sys.modules.get("backtest")
    pkg_is_stub = bt_pkg is not None and getattr(bt_pkg, "_tsukasa_stub", False)

    for key in list(sys.modules.keys()):
        if key.startswith("backtest"):
            mod = sys.modules.get(key)
            if mod is None:
                continue
            if getattr(mod, "_tsukasa_stub", False) or pkg_is_stub:
                saved[key] = sys.modules.pop(key)
    yield
    # Restore stub modules so polluter tests still work
    for key, mod in saved.items():
        if key not in sys.modules:
            sys.modules[key] = mod


class TestCanaryDisable:
    """Verify canary is properly disabled when tp_sl_pct=0.0."""

    def test_canary_disabled_by_default(self):
        """TestCanaryStrategy with default tp_sl_pct=0.0 is disabled."""
        from strategies.test_canary import TestCanaryStrategy

        canary = TestCanaryStrategy()  # default tp_sl_pct=0.0
        assert canary.enabled is False
        assert canary.tp_sl_pct == 0.0

    def test_canary_explicit_disable(self):
        """TestCanaryStrategy(tp_sl_pct=0.0) is explicitly disabled."""
        from strategies.test_canary import TestCanaryStrategy

        canary = TestCanaryStrategy(tp_sl_pct=0.0)
        assert canary.enabled is False

    def test_canary_evaluate_returns_none_when_disabled(self):
        """evaluate() returns None when canary is disabled."""
        from datetime import datetime, timezone

        from backtest.types import Bar
        from strategies.test_canary import TestCanaryStrategy

        canary = TestCanaryStrategy(tp_sl_pct=0.0)
        bar = Bar(
            time=datetime.now(timezone.utc),
            open=1.0,
            high=1.1,
            low=0.9,
            close=1.05,
            volume=100,
        )
        state = MagicMock()
        state.bars = [bar]
        result = canary.evaluate(state)
        assert result is None

    def test_canary_enabled_when_tp_sl_pct_positive(self):
        """TestCanaryStrategy with tp_sl_pct>0 is enabled."""
        from strategies.test_canary import TestCanaryStrategy

        canary = TestCanaryStrategy(tp_sl_pct=0.005)
        assert canary.enabled is True

    def test_canary_warning_log_when_enabled(self, caplog):
        """evaluate() emits WARNING log when canary is enabled (hardening)."""
        from datetime import datetime, timezone

        from backtest.types import Bar
        from strategies.test_canary import TestCanaryStrategy

        canary = TestCanaryStrategy(tp_sl_pct=0.005)

        bar = Bar(
            time=datetime.now(timezone.utc),
            open=1.0,
            high=1.1,
            low=0.9,
            close=1.05,
            volume=100,
        )
        state = MagicMock()
        state.bars = [bar]

        with caplog.at_level(logging.WARNING, logger="ayumi.test_canary"):
            canary.evaluate(state)

        assert any(
            "canary" in record.message.lower() and "enabled" in record.message.lower() for record in caplog.records
        ), f"Expected WARNING about canary being enabled, got: {[r.message for r in caplog.records]}"


class TestCanaryEnvGating:
    """Verify env var gating logic for canary re-enable."""

    def test_env_var_not_set_means_disabled(self):
        """Without AYUMI_ENABLE_CANARY env var, canary should construct as disabled."""
        from strategies.test_canary import TestCanaryStrategy

        # Ensure env var is not set
        old = os.environ.pop("AYUMI_ENABLE_CANARY", None)
        try:
            canary = TestCanaryStrategy.from_env()
            assert canary.enabled is False
            assert canary.tp_sl_pct == 0.0
        finally:
            if old is not None:
                os.environ["AYUMI_ENABLE_CANARY"] = old

    def test_env_var_set_to_1_enables_canary(self):
        """With AYUMI_ENABLE_CANARY=1, canary is enabled with 0.005 tp_sl_pct."""
        from strategies.test_canary import TestCanaryStrategy

        old = os.environ.pop("AYUMI_ENABLE_CANARY", None)
        try:
            os.environ["AYUMI_ENABLE_CANARY"] = "1"
            canary = TestCanaryStrategy.from_env()
            assert canary.enabled is True
            assert canary.tp_sl_pct == 0.005
        finally:
            if old is not None:
                os.environ["AYUMI_ENABLE_CANARY"] = old
            else:
                os.environ.pop("AYUMI_ENABLE_CANARY", None)
