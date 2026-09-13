"""Tournament harness for ranked multi-strategy scorecard generation.

The tournament package registers existing strategies from
``src.forex_bot.strategies.registry`` and runs each one (unmodified)
against a single historical window, emitting a ranked JSON + console
scorecard with FTMO-constraint columns (3% daily-DD breaches, 10%
total-DD breaches).

This is the walking-skeleton pivot (card db04d5b5) — the minimal
shape that opens the tournament milestone. Subsequent cards
(decomposition notes live in
``docs/plans/ayumi-tournament-harness-spec.md``) grow shared-engine
coupling, intraday equity snapshot fidelity, and multi-symbol matrix
support.
"""

from tournament.harness import (
    STRATEGY_CLASS_MAP,
    TournamentEmptyWindow,
    TournamentHarness,
    load_bars_for_window,
    resolve_default_duckdb_path,
)
from tournament.scorecard import (
    ScorecardRow,
    build_scorecard_row,
    render_console_table,
    render_scorecard_json,
)

__all__ = [
    "TournamentHarness",
    "TournamentEmptyWindow",
    "STRATEGY_CLASS_MAP",
    "load_bars_for_window",
    "resolve_default_duckdb_path",
    "ScorecardRow",
    "build_scorecard_row",
    "render_console_table",
    "render_scorecard_json",
]
