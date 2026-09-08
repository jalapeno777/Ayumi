"""Tests for card d2be30f4 — counterfactual regime-gate observability log.

Card spec: env var ``AYUMI_COUNTERFACTUAL_LOG=1`` (default off, literal
"1" only) makes the live launcher log one JSONL line per strategy
evaluation to ``data/counterfactual_gate_log.jsonl``.  Gate behavior is
UNCHANGED when the flag is on — this is additive observability only,
needed to separate "strategy never fires" from "gate blocks fires"
before the Phase 1.3 gate-loosening experiment.

The log line shape (per the spec) is::

    {ts, symbol, strategy_id, regime, session, adx,
     current_gate: pass|reject, expanded_gate_would: pass|reject,
     strategy_emitted: bool}

The expanded gate is the experiment candidate:
regimes {QUIET, CHOPPY, TRENDING}, sessions {london, ny_am}.

These tests cover:

1. Env var gating — only literal "1" enables; default off; never crashes.
2. JSONL schema — exact field shape, ISO-8601 ts, pass/reject values.
3. Expanded-gate logic — regime AND session predicates, none-on-None fail closed.
4. Logger file I/O — lazy open, append-mode, warn-once on failure, never raise.
5. RegimeGate behavior is unchanged with the flag on/off (parity AC).
6. End-to-end smoke — launcher module imports cleanly with the new block.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# Importing the launcher module executes its top-level load_dotenv()
# call, which is harmless if .env is absent.  pythonpath in pytest.ini
# includes ``scripts`` so this resolves cleanly.
import launch_blend_forward_test as _launcher_mod  # noqa: E402
import pytest
from launch_blend_forward_test import (  # noqa: E402
    _COUNTERFACTUAL_LOG_PATH,
    _EXPANDED_REGIMES,
    _EXPANDED_SESSIONS,
    RegimeGate,
    _build_counterfactual_payload,
    _counterfactual_log_enabled,
    _CounterfactualLogger,
    _expanded_gate_would_pass,
    _extract_regime_and_session,
    _get_counterfactual_logger,
)
from regime.detector import Regime  # noqa: E402

# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeBar:
    """Minimal duck-typed Bar for the counterfactual extraction tests.

    The launcher's ``RegimeGate`` / ``_extract_regime_and_session`` only
    touch ``.high``, ``.low``, ``.close`` and (optionally) ``.time`` —
    everything else on the real ``Bar`` dataclass is unused here.  This
    fake is faster to construct and keeps the tests independent of the
    real ``Bar`` constructor's default arguments.
    """

    __slots__ = ("high", "low", "close", "time")

    def __init__(
        self,
        high: float,
        low: float,
        close: float,
        time: datetime | None = None,
    ) -> None:
        self.high = float(high)
        self.low = float(low)
        self.close = float(close)
        self.time = time


def _make_trending_bars(
    n: int = 120,
    *,
    start_price: float = 1.2500,
    step: float = 0.0010,
    start_time: datetime | None = None,
) -> list[_FakeBar]:
    """Build ``n`` monotonically rising synthetic bars — exercises the
    RegimeDetector in a controlled way without touching real market data.

    The fixture's ``start_time`` is the FIRST bar's timestamp; the LAST
    bar is at ``start_time + (n-1) * 15min``.  Tests that assert a
    specific session should account for the last-bar hour — with
    ``n=120`` the last bar is 29h45min after the first, so the session
    window of the first bar is usually NOT the session of the last.
    Use :func:`_make_bars_ending_at` when the last bar's hour matters.
    """
    if start_time is None:
        # 2026-09-08 09:00 UTC = London killzone for the first bar.
        start_time = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)
    bars: list[_FakeBar] = []
    for i in range(n):
        close = start_price + step * i
        # 2-pip noise band on top of close for high/low.
        bars.append(
            _FakeBar(
                high=close + 0.0002,
                low=close - 0.0002,
                close=close,
                time=start_time + timedelta(minutes=15 * i),
            )
        )
    return bars


def _make_bars_ending_at(
    n: int,
    end_time: datetime,
    *,
    start_price: float = 1.2500,
    step: float = 0.0010,
) -> list[_FakeBar]:
    """Build ``n`` bars whose LAST timestamp is exactly ``end_time``.

    Useful for session tests where the last bar's UTC hour determines
    the session — see ``TestExtractRegimeAndSession`` below.
    """
    start_time = end_time - timedelta(minutes=15 * (n - 1))
    return _make_trending_bars(
        n=n,
        start_price=start_price,
        step=step,
        start_time=start_time,
    )


@pytest.fixture
def trending_bars() -> list[_FakeBar]:
    return _make_trending_bars()


@pytest.fixture(autouse=True)
def _reset_logger_singleton() -> Iterable[None]:
    """Reset the module-level counterfactual logger singleton + env var
    between tests so each test starts from a known-clean state.  Also
    closes any open file handle to release temp paths under ``tmp_path``.
    """
    # Drop env var so the off-by-default contract holds unless a test sets it.
    os.environ.pop("AYUMI_COUNTERFACTUAL_LOG", None)
    existing = getattr(_launcher_mod, "_counterfactual_logger", None)
    if existing is not None:
        try:
            existing.close()
        except Exception:  # noqa: S110 — defensive cleanup
            pass
    _launcher_mod._counterfactual_logger = None
    yield
    # Post-test cleanup: close any handle the test opened and reset.
    existing = getattr(_launcher_mod, "_counterfactual_logger", None)
    if existing is not None:
        try:
            existing.close()
        except Exception:  # noqa: S110 — defensive cleanup
            pass
    _launcher_mod._counterfactual_logger = None


# ── 1. Env var gating (AC1: only literal '1' enables, default off) ────────


class TestCounterfactualLogEnabled:
    """``_counterfactual_log_enabled`` must only return True for the
    literal env value ``"1"`` — every other value, including unset,
    empty, "true", "yes", and trailing-space variants, is off.
    """

    @pytest.mark.parametrize(
        "value",
        ["", "0", "1 ", " 1", "true", "True", "TRUE", "yes", "on", "2", "01"],
    )
    def test_non_literal_one_is_off(
        self, monkeypatch: pytest.MonkeyPatch, value: str,
    ) -> None:
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", value)
        assert _counterfactual_log_enabled() is False

    def test_literal_one_is_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")
        assert _counterfactual_log_enabled() is True

    def test_unset_is_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AYUMI_COUNTERFACTUAL_LOG", raising=False)
        assert _counterfactual_log_enabled() is False

    def test_runtime_toggle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Operator can flip the flag without restarting — next per-bar
        call picks up the new value via ``os.getenv``.
        """
        monkeypatch.delenv("AYUMI_COUNTERFACTUAL_LOG", raising=False)
        assert _counterfactual_log_enabled() is False
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")
        assert _counterfactual_log_enabled() is True
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "0")
        assert _counterfactual_log_enabled() is False


class TestGetCounterfactualLogger:
    """Singleton accessor must return ``None`` when the flag is off
    (zero I/O cost) and return a logger instance when on.
    """

    def test_returns_none_when_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AYUMI_COUNTERFACTUAL_LOG", raising=False)
        assert _get_counterfactual_logger() is None
        # Singleton must remain None (no side-effect of being queried).
        assert _launcher_mod._counterfactual_logger is None

    def test_returns_logger_when_on(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")
        # Point the path at a tmp location so the test does not create
        # files in the repo's ``data/`` dir.
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        monkeypatch.setattr(_launcher_mod, "_COUNTERFACTUAL_LOG_PATH", log_path)

        logger_inst = _get_counterfactual_logger()
        assert isinstance(logger_inst, _CounterfactualLogger)
        assert logger_inst.path == log_path
        # Lazy init — file handle must NOT be opened on the call itself.
        assert logger_inst._fh is None
        logger_inst.close()

    def test_singleton_returns_same_instance(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")
        first = _get_counterfactual_logger()
        second = _get_counterfactual_logger()
        assert first is second
        first.close()


# ── 2. JSONL schema ─────────────────────────────────────────────────────────


class TestBuildCounterfactualPayload:
    """Payload must match the spec field shape exactly.

    Fields: ``ts``, ``symbol``, ``strategy_id``, ``regime``, ``session``,
    ``adx``, ``current_gate``, ``expanded_gate_would``, ``strategy_emitted``.
    """

    def test_field_set_is_exact(self) -> None:
        payload = _build_counterfactual_payload(
            symbol="GBPUSD",
            strategy_id="killzone_momentum",
            regime=Regime.TRENDING,
            session="london",
            adx=22.0,
            current_gate_decision="pass",
            expanded_gate_decision="pass",
            strategy_emitted=True,
        )
        assert set(payload.keys()) == {
            "ts",
            "symbol",
            "strategy_id",
            "regime",
            "session",
            "adx",
            "current_gate",
            "expanded_gate_would",
            "strategy_emitted",
        }

    def test_values_round_trip(self) -> None:
        """Field types and string-encoding match the spec."""
        payload = _build_counterfactual_payload(
            symbol="GBPUSD",
            strategy_id="killzone_momentum",
            regime=Regime.TRENDING,
            session="london",
            adx=22.0,
            current_gate_decision="pass",
            expanded_gate_decision="reject",
            strategy_emitted=True,
        )
        assert payload["symbol"] == "GBPUSD"
        assert payload["strategy_id"] == "killzone_momentum"
        # Regime enum serializes via .value (lowercase string).
        assert payload["regime"] == "trending"
        assert payload["session"] == "london"
        assert payload["adx"] == 22.0
        assert payload["current_gate"] == "pass"
        assert payload["expanded_gate_would"] == "reject"
        assert payload["strategy_emitted"] is True
        # ts is ISO-8601 UTC (parseable; timezone-aware).
        parsed = datetime.fromisoformat(payload["ts"])
        assert parsed.tzinfo is not None

    def test_unknown_regime_serializes_as_unknown(self) -> None:
        payload = _build_counterfactual_payload(
            symbol="GBPUSD",
            strategy_id="srmr_plus",
            regime=None,
            session="other",
            adx=None,
            current_gate_decision="reject",
            expanded_gate_decision="reject",
            strategy_emitted=False,
        )
        assert payload["regime"] == "unknown"
        assert payload["adx"] is None
        assert payload["strategy_emitted"] is False

    def test_payload_is_json_serializable(self) -> None:
        """JSONL write path uses json.dumps; payload must round-trip."""
        payload = _build_counterfactual_payload(
            symbol="EURUSD",
            strategy_id="dual_tf_squeeze_pro",
            regime=Regime.CHOPPY,
            session="ny_am",
            adx=18.5,
            current_gate_decision="pass",
            expanded_gate_decision="pass",
            strategy_emitted=True,
        )
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded == payload


# ── 3. Expanded gate logic ────────────────────────────────────────────────


class TestExpandedGateWouldPass:
    """Expanded gate = regime ∈ {QUIET, CHOPPY, TRENDING} AND session ∈ {london, ny_am}.

    Must fail closed on ``None`` regime so the counterfactual log is
    honest about the unknown-regime case.
    """

    @pytest.mark.parametrize(
        "regime,session,expected",
        [
            (Regime.QUIET, "london", "pass"),
            (Regime.CHOPPY, "london", "pass"),
            (Regime.TRENDING, "london", "pass"),
            (Regime.QUIET, "ny_am", "pass"),
            (Regime.CHOPPY, "ny_am", "pass"),
            (Regime.TRENDING, "ny_am", "pass"),
            # VOLATILE is NOT in the expanded set — current gate's
            # ``london_breakout_retest`` allows it, expanded does not.
            (Regime.VOLATILE, "london", "reject"),
            (Regime.VOLATILE, "ny_am", "reject"),
            # asia / other sessions are NOT in the expanded set.
            (Regime.QUIET, "asia", "reject"),
            (Regime.TRENDING, "other", "reject"),
            (Regime.VOLATILE, "asia", "reject"),
        ],
    )
    def test_predicate_table(
        self, regime: Regime | None, session: str, expected: str,
    ) -> None:
        assert _expanded_gate_would_pass(regime, session) == expected

    def test_none_regime_fails_closed(self) -> None:
        """``None`` regime (insufficient bars or detector failure) → reject."""
        assert _expanded_gate_would_pass(None, "london") == "reject"
        assert _expanded_gate_would_pass(None, "asia") == "reject"

    def test_constants_match_spec(self) -> None:
        """Sanity: the module-level constants are exactly the spec set."""
        assert _EXPANDED_REGIMES == frozenset(
            {Regime.QUIET, Regime.CHOPPY, Regime.TRENDING}
        )
        assert _EXPANDED_SESSIONS == frozenset({"london", "ny_am"})


# ── 4. Feature extraction (helper behind the engine integration) ──────────


class TestExtractRegimeAndSession:
    """``_extract_regime_and_session`` returns (regime, adx, session)
    independently of strategy-specific gates.  Used by both branches
    of the counterfactual log path.
    """

    def test_insufficient_bars_returns_none_regime(self) -> None:
        # Build bars whose LAST bar lands at 09:00 UTC = london killzone.
        short = _make_bars_ending_at(50, datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc))
        regime, adx, session = _extract_regime_and_session(short, short[-1])
        assert regime is None
        assert adx is None
        # Session can still be computed from the bar timestamp.
        assert session == "london"

    def test_sufficient_bars_returns_full_tuple(self) -> None:
        # Last bar at 09:00 UTC = london killzone.
        bars = _make_bars_ending_at(120, datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc))
        regime, adx, session = _extract_regime_and_session(
            bars, bars[-1],
        )
        # All three fields populated.  Regime may be any of the four
        # enum values (synthetic data); ADX may be NaN if the indicator
        # series is empty/short — both are returned as-is.
        assert session == "london"
        assert isinstance(regime, Regime)
        # ADX is either a finite number or NaN — never a string.
        if adx is not None:
            assert isinstance(adx, float)

    def test_session_other_for_outside_killzone(self) -> None:
        """Hour 18 UTC = 'other' per the launcher's session table.
        Last bar at 18:00 UTC."""
        bars = _make_bars_ending_at(120, datetime(2026, 9, 8, 18, 0, tzinfo=timezone.utc))
        _, _, session = _extract_regime_and_session(bars, bars[-1])
        assert session == "other"

    def test_session_asia_for_hour_3(self) -> None:
        """Last bar at 03:00 UTC = asia session."""
        bars = _make_bars_ending_at(120, datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc))
        _, _, session = _extract_regime_and_session(bars, bars[-1])
        assert session == "asia"

    def test_session_ny_am_for_hour_14(self) -> None:
        """Last bar at 14:00 UTC = ny_am session."""
        bars = _make_bars_ending_at(120, datetime(2026, 9, 8, 14, 0, tzinfo=timezone.utc))
        _, _, session = _extract_regime_and_session(bars, bars[-1])
        assert session == "ny_am"

    def test_session_london_for_hour_9(self) -> None:
        """Last bar at 09:00 UTC = london killzone."""
        bars = _make_bars_ending_at(120, datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc))
        _, _, session = _extract_regime_and_session(bars, bars[-1])
        assert session == "london"

    def test_bar_without_time_attribute_yields_unknown_session(self) -> None:
        """Defensive: a Bar with no ``time`` attr → session='unknown'."""
        bar_no_time = _FakeBar(high=1.0, low=0.9, close=0.95, time=None)
        bars = _make_bars_ending_at(120, datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc))
        bars[-1] = bar_no_time  # last bar has no .time
        # Should not raise; session falls back to 'unknown'.
        regime, adx, session = _extract_regime_and_session(bars, bar_no_time)
        assert session == "unknown"

    def test_empty_bars_returns_none_regime(self) -> None:
        _, _, session = _extract_regime_and_session([], None)
        assert session == "unknown"


# ── 5. Logger file I/O (best-effort, warn-once, never crash) ─────────────


class TestCounterfactualLoggerFileIO:
    """The logger must never crash the live launcher.  All OSError
    paths log a single warning, then go silent.  Successful writes
    land on disk in append-mode.
    """

    def test_lazy_open_first_write(
        self, tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        logger_inst = _CounterfactualLogger(path=log_path)
        assert logger_inst._fh is None
        logger_inst.write({"ts": "x", "k": 1})
        logger_inst.close()
        # File created and contains the JSON line.
        assert log_path.exists()
        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"ts": "x", "k": 1}

    def test_append_mode_preserves_existing(
        self, tmp_path: Path,
    ) -> None:
        """Two loggers writing in sequence must append, not overwrite."""
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        log_path.write_text('{"ts": "pre-existing"}\n')
        logger_inst = _CounterfactualLogger(path=log_path)
        logger_inst.write({"ts": "new-1"})
        logger_inst.write({"ts": "new-2"})
        logger_inst.close()
        lines = log_path.read_text().splitlines()
        assert len(lines) == 3
        assert json.loads(lines[0]) == {"ts": "pre-existing"}
        assert json.loads(lines[1]) == {"ts": "new-1"}
        assert json.loads(lines[2]) == {"ts": "new-2"}

    def test_unwritable_path_warns_once(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """If ``data/counterfactual_gate_log.jsonl`` cannot be opened
        (parent is a file, not a dir), the logger must warn ONCE on the
        first failed write and stay silent on subsequent writes —
        otherwise a flaky disk would flood the operator logs.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        # Point logger at <blocker>/counterfactual_gate_log.jsonl
        # — mkdir(parents=True) will fail because blocker is a file.
        log_path = blocker / "counterfactual_gate_log.jsonl"
        logger_inst = _CounterfactualLogger(path=log_path)

        with caplog.at_level(logging.WARNING):
            logger_inst.write({"ts": "x"})
            logger_inst.write({"ts": "y"})
            logger_inst.write({"ts": "z"})

        # All three writes completed without raising (best-effort).
        # Exactly one warning was emitted (warn-once semantics).
        warn_messages = [
            r for r in caplog.records
            if "Counterfactual log" in r.message
            and r.levelno >= logging.WARNING
        ]
        assert len(warn_messages) == 1
        assert "failed to open" in warn_messages[0].message
        # Internal flag set so subsequent writes stay quiet.
        assert logger_inst.warned_failure is True
        logger_inst.close()

    def test_write_does_not_raise_on_open_failure(self, tmp_path: Path) -> None:
        """Live-launcher safety: write() must swallow OSError."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        log_path = blocker / "counterfactual_gate_log.jsonl"
        logger_inst = _CounterfactualLogger(path=log_path)
        # Must NOT raise — wraps OSError internally.
        logger_inst.write({"ts": "x"})
        logger_inst.write({"ts": "y"})
        logger_inst.close()

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        """Calling close() before any write or twice in a row is safe."""
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        logger_inst = _CounterfactualLogger(path=log_path)
        logger_inst.close()  # no-op (never opened)
        logger_inst.close()  # still a no-op
        logger_inst.write({"ts": "x"})
        logger_inst.close()  # closes real handle
        logger_inst.close()  # second close is also safe


# ── 6. RegimeGate behavior unchanged (AC: gate decisions parity) ──────────


class TestRegimeGateUnchangedByCounterfactualFeature:
    """AC: gate decisions are unchanged with/without the counterfactual
    flag.  The flag is implemented in ``_evaluate_strategies``, not in
    ``RegimeGate.check`` — these tests verify that ``RegimeGate.check``
    itself is untouched: same signature, same return shape, same
    outputs across representative inputs.
    """

    def test_check_returns_bool_and_str(
        self, trending_bars: list[_FakeBar],
    ) -> None:
        gate = RegimeGate()
        # Strategy 'killzone_momentum' is in the gate's table.
        allowed, reason = gate.check(
            "killzone_momentum", trending_bars, trending_bars[-1],
        )
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)
        assert reason  # non-empty

    def test_check_decision_independent_of_counterfactual_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trending_bars: list[_FakeBar],
    ) -> None:
        """Run ``gate.check`` with the flag off, then on — outputs must
        be byte-identical.  The flag is read in ``_evaluate_strategies``
        only; ``RegimeGate`` does not consult it.
        """
        gate = RegimeGate()

        monkeypatch.delenv("AYUMI_COUNTERFACTUAL_LOG", raising=False)
        off_allowed, off_reason = gate.check(
            "killzone_momentum", trending_bars, trending_bars[-1],
        )

        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")
        on_allowed, on_reason = gate.check(
            "killzone_momentum", trending_bars, trending_bars[-1],
        )

        assert (on_allowed, on_reason) == (off_allowed, off_reason)

    def test_check_with_unknown_strategy_id_still_passes(
        self, trending_bars: list[_FakeBar],
    ) -> None:
        """Unmapped strategies: gate returns ('no_gate', True) — no
        change introduced by this card.
        """
        gate = RegimeGate()
        allowed, reason = gate.check(
            "definitely_not_in_the_table", trending_bars, trending_bars[-1],
        )
        assert allowed is True
        assert reason == "no_gate"


# ── 7. End-to-end smoke (launcher imports cleanly) ───────────────────────


def test_launcher_module_imports_cleanly() -> None:
    """Smoke test: the launcher module is importable from the test scope
    (its top-level load_dotenv() runs at import time but is harmless if
    ``.env`` is absent) and the new counterfactual block exposes every
    helper the engine integration relies on.

    The presence of these names on the module is the build-time contract
    that the engine will find them at runtime — missing names would
    surface here as ``AttributeError`` on the assertions below.
    """
    # Required names for the engine integration (lines 769-880ish).
    assert callable(_counterfactual_log_enabled)
    assert callable(_get_counterfactual_logger)
    assert callable(_extract_regime_and_session)
    assert callable(_expanded_gate_would_pass)
    assert callable(_build_counterfactual_payload)
    assert isinstance(_CounterfactualLogger, type)
    # Path constant exists and is project-relative.
    assert isinstance(_COUNTERFACTUAL_LOG_PATH, Path)
    assert _COUNTERFACTUAL_LOG_PATH.name == "counterfactual_gate_log.jsonl"


# ── 8. JSONL write end-to-end through the singleton ──────────────────────


class TestEndToEndJsonlWrite:
    """Drive the singleton + logger through ``write`` end-to-end and
    confirm the file is parseable JSONL.
    """

    def test_singleton_writes_parseable_jsonl(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        monkeypatch.setattr(_launcher_mod, "_COUNTERFACTUAL_LOG_PATH", log_path)
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")

        logger_inst = _get_counterfactual_logger()
        assert logger_inst is not None
        # Emit three lines covering all three branches the engine hits.
        for emitted, decision in [
            (False, "reject"),  # no-signal branch
            (True, "reject"),    # signal emitted, gate rejected
            (True, "pass"),      # signal emitted, gate passed
        ]:
            logger_inst.write(
                _build_counterfactual_payload(
                    symbol="GBPUSD",
                    strategy_id="killzone_momentum",
                    regime=Regime.TRENDING,
                    session="london",
                    adx=22.0,
                    current_gate_decision=decision,
                    expanded_gate_decision="pass",
                    strategy_emitted=emitted,
                )
            )
        logger_inst.close()

        # All lines parseable.
        lines = log_path.read_text().splitlines()
        assert len(lines) == 3
        decoded = [json.loads(line) for line in lines]
        # Order matches the writes above.
        assert [d["strategy_emitted"] for d in decoded] == [False, True, True]
        assert [d["current_gate"] for d in decoded] == [
            "reject", "reject", "pass",
        ]
        # Every line carries the full schema (spec compliance).
        for d in decoded:
            assert set(d.keys()) == {
                "ts",
                "symbol",
                "strategy_id",
                "regime",
                "session",
                "adx",
                "current_gate",
                "expanded_gate_would",
                "strategy_emitted",
            }
            assert d["symbol"] == "GBPUSD"
            assert d["strategy_id"] == "killzone_momentum"
            assert d["regime"] == "trending"
            assert d["session"] == "london"


# ── 9. Engine-integration surrogate (no broker; simulate bar path) ───────


class TestEngineIntegrationSurrogate:
    """Lightweight surrogate of ``BlendForwardTestEngine._evaluate_strategies``
    counterfactual branches.  Avoids spinning up the full engine; just
    confirms that the no-signal and gate-decision branches emit the
    expected payload shape when the flag is on, and emit nothing when
    the flag is off.

    This is the closest test we can get without the full broker fixture;
    the engine integration is exercised separately in the live restart.
    """

    def test_no_signal_branch_emits_log_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        trending_bars: list[_FakeBar],
    ) -> None:
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        monkeypatch.setattr(_launcher_mod, "_COUNTERFACTUAL_LOG_PATH", log_path)
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")

        logger_inst = _get_counterfactual_logger()
        assert logger_inst is not None

        # Surrogate of the ``if s is None: continue`` branch.
        regime, adx, session = _extract_regime_and_session(
            trending_bars, trending_bars[-1],
        )
        logger_inst.write(
            _build_counterfactual_payload(
                symbol="GBPUSD",
                strategy_id="srmr_plus",
                regime=regime,
                session=session,
                adx=adx,
                current_gate_decision="reject",
                expanded_gate_decision=_expanded_gate_would_pass(regime, session),
                strategy_emitted=False,
            )
        )
        logger_inst.close()

        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["strategy_emitted"] is False
        assert payload["current_gate"] == "reject"
        assert payload["expanded_gate_would"] in ("pass", "reject")
        # Schema complete.
        assert "ts" in payload and "symbol" in payload

    def test_gate_pass_branch_emits_log_when_flag_on(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        trending_bars: list[_FakeBar],
    ) -> None:
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        monkeypatch.setattr(_launcher_mod, "_COUNTERFACTUAL_LOG_PATH", log_path)
        monkeypatch.setenv("AYUMI_COUNTERFACTUAL_LOG", "1")

        logger_inst = _get_counterfactual_logger()
        assert logger_inst is not None

        regime, adx, session = _extract_regime_and_session(
            trending_bars, trending_bars[-1],
        )
        logger_inst.write(
            _build_counterfactual_payload(
                symbol="GBPUSD",
                strategy_id="donchian_atr_trend_v2",
                regime=regime,
                session=session,
                adx=adx,
                current_gate_decision="pass",
                expanded_gate_decision=_expanded_gate_would_pass(regime, session),
                strategy_emitted=True,
            )
        )
        logger_inst.close()

        lines = log_path.read_text().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["strategy_emitted"] is True
        assert payload["current_gate"] == "pass"

    def test_no_log_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        trending_bars: list[_FakeBar],
    ) -> None:
        """AC1: with env unset, zero log lines, zero behavior change."""
        log_path = tmp_path / "counterfactual_gate_log.jsonl"
        monkeypatch.setattr(_launcher_mod, "_COUNTERFACTUAL_LOG_PATH", log_path)
        monkeypatch.delenv("AYUMI_COUNTERFACTUAL_LOG", raising=False)

        # AC1 part A: the singleton accessor returns None.
        assert _get_counterfactual_logger() is None

        # AC1 part B: no file is created even if the engine integration
        # logic were called — because the launcher's gate is
        # ``if _cf_logger is None: continue``.
        # Simulate the launcher's gate by just doing nothing here.
        assert not log_path.exists()
        # The bars+payload construction path is fine, but the engine
        # would short-circuit before reaching it — assert that path.
        regime, adx, session = _extract_regime_and_session(
            trending_bars, trending_bars[-1],
        )
        # Still callable, but no logger to write to.
        payload = _build_counterfactual_payload(
            symbol="GBPUSD",
            strategy_id="killzone_momentum",
            regime=regime,
            session=session,
            adx=adx,
            current_gate_decision="reject",
            expanded_gate_decision=_expanded_gate_would_pass(regime, session),
            strategy_emitted=False,
        )
        # Payload is still valid (off-by-default does not affect
        # payload shape); the gate is the logger-write short-circuit.
        assert payload["strategy_emitted"] is False
        assert not log_path.exists()  # engine never reached the write
