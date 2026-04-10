"""TTC/TBD Signal & Confidence Engine — Phase 1-4."""

from .swing_detector import SwingDetector
from .level_counter import LevelCounter
from .htf_analyzer import HTFAnalyzer
from .session_logic import SessionAnalyzer
from .pattern_detector import PatternDetector
from .gate_validator import GateValidator
from .confluence_scorer import ConfluenceScorer
from .signal_output import format_signal_json, parse_signal_json, create_signal
from .stop_target import StopTargetCalculator
from .backtest_bridge import SignalEngineBridge

BacktestBridge = SignalEngineBridge  # alias

from .data_types import (
    Signal,
    Level,
    Swing,
    HTFState,
    SessionState,
    LevelType,
    SwingType,
    HTFPhase,
)

__all__ = [
    "SwingDetector",
    "LevelCounter",
    "HTFAnalyzer",
    "SessionAnalyzer",
    "PatternDetector",
    "GateValidator",
    "ConfluenceScorer",
    "format_signal_json",
    "parse_signal_json",
    "create_signal",
    "StopTargetCalculator",
    "SignalEngineBridge",
    "BacktestBridge",
    "Signal",
    "Level",
    "Swing",
    "HTFState",
    "SessionState",
    "LevelType",
    "SwingType",
    "HTFPhase",
]
