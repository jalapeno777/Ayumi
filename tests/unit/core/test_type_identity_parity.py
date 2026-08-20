"""
Type-identity parity test between core.types and backtest.types.

After the fix in sub-card B, backtest/types.py now re-exports TradeDirection
and TradeOutcome from core/types.py (same pattern already used for ExitReason
and SessionType). All four types now share identity across module boundaries.

Historical note: This was the root cause of D-011 (zero-trade strategies).
Strategies emitted signals using core.types.TradeDirection, but the backtest
engine compared against backtest.types.TradeDirection. The identity mismatch
silently dropped every signal.
"""

from core import types as core_types  # noqa: I001
from backtest import types as backtest_types


# ---------------------------------------------------------------------------
# IDENTITY PARITY: All types now share identity (bug fixed)
# ---------------------------------------------------------------------------


class TestTradeDirectionParity:
    """TradeDirection is re-exported from core — identity holds."""

    def test_members_are_identical(self):
        assert core_types.TradeDirection.LONG is backtest_types.TradeDirection.LONG, (
            "TradeDirection members should share identity after fix"
        )

    def test_classes_are_same_type(self):
        assert type(core_types.TradeDirection.LONG) is type(backtest_types.TradeDirection.LONG), (
            "TradeDirection should be the same enum class after fix"
        )

    def test_equality_holds(self):
        assert core_types.TradeDirection.LONG == backtest_types.TradeDirection.LONG, (
            "Cross-module TradeDirection equality should hold after fix"
        )

    def test_membership_check_holds(self):
        """Python 3.12+ Enum.__contains__ matches by value."""
        assert core_types.TradeDirection.LONG in backtest_types.TradeDirection, "Enum membership should hold after fix"


class TestTradeOutcomeParity:
    """TradeOutcome is re-exported from core — identity holds."""

    def test_members_are_identical(self):
        assert core_types.TradeOutcome.WIN is backtest_types.TradeOutcome.WIN, (
            "TradeOutcome members should share identity after fix"
        )

    def test_classes_are_same_type(self):
        assert type(core_types.TradeOutcome.WIN) is type(backtest_types.TradeOutcome.WIN), (
            "TradeOutcome should be the same enum class after fix"
        )

    def test_equality_holds(self):
        assert core_types.TradeOutcome.WIN == backtest_types.TradeOutcome.WIN, (
            "Cross-module TradeOutcome equality should hold after fix"
        )


# ---------------------------------------------------------------------------
# POSITIVE CONTROL: These types were already correctly re-exported
# ---------------------------------------------------------------------------


class TestExitReasonParity:
    """ExitReason was already re-exported — identity holds (positive control)."""

    def test_members_are_identical(self):
        assert core_types.ExitReason.STOP_LOSS is backtest_types.ExitReason.STOP_LOSS, (
            "ExitReason should share identity (already re-exported from core)"
        )

    def test_classes_are_same_type(self):
        assert type(core_types.ExitReason.STOP_LOSS) is type(backtest_types.ExitReason.STOP_LOSS), (
            "ExitReason should be the same enum class (already re-exported from core)"
        )


class TestSessionTypeParity:
    """SessionType was already re-exported — identity holds (positive control)."""

    def test_members_are_identical(self):
        assert core_types.SessionType.ASIAN is backtest_types.SessionType.ASIAN, (
            "SessionType should share identity (already re-exported from core)"
        )

    def test_classes_are_same_type(self):
        assert type(core_types.SessionType.ASIAN) is type(backtest_types.SessionType.ASIAN), (
            "SessionType should be the same enum class (already re-exported from core)"
        )
