"""Execution simulation for realistic backtesting.

Models spread, slippage, and latency effects with session-aware
spread modelling and optional volatility scaling.
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np

from config.sessions import TradingSession, get_trading_session


# ---------------------------------------------------------------------------
# Session-aware spread table (base spreads in pips)
# Values reflect typical raw-spread averages from IC Markets / Pepperstone.
# Multiply by pip_size (0.0001 for non-JPY, 0.01 for JPY) to get price impact.
# ---------------------------------------------------------------------------
SPREAD_TABLE: dict[str, dict[TradingSession, float]] = {
    "EURUSD": {
        TradingSession.ASIAN: 1.0,
        TradingSession.LONDON: 0.5,
        TradingSession.NY_OVERLAP: 0.3,
        TradingSession.NY_AFTERNOON: 0.7,
        TradingSession.OFF_HOURS: 1.5,
    },
    "GBPUSD": {
        TradingSession.ASIAN: 1.5,
        TradingSession.LONDON: 0.8,
        TradingSession.NY_OVERLAP: 0.5,
        TradingSession.NY_AFTERNOON: 1.0,
        TradingSession.OFF_HOURS: 2.0,
    },
    "USDJPY": {
        TradingSession.ASIAN: 0.8,
        TradingSession.LONDON: 0.7,
        TradingSession.NY_OVERLAP: 0.4,
        TradingSession.NY_AFTERNOON: 0.8,
        TradingSession.OFF_HOURS: 1.5,
    },
    "USDCHF": {
        TradingSession.ASIAN: 1.5,
        TradingSession.LONDON: 1.0,
        TradingSession.NY_OVERLAP: 0.7,
        TradingSession.NY_AFTERNOON: 1.2,
        TradingSession.OFF_HOURS: 2.0,
    },
    "AUDUSD": {
        TradingSession.ASIAN: 1.2,
        TradingSession.LONDON: 1.0,
        TradingSession.NY_OVERLAP: 0.6,
        TradingSession.NY_AFTERNOON: 0.9,
        TradingSession.OFF_HOURS: 1.8,
    },
    "USDCAD": {
        TradingSession.ASIAN: 1.5,
        TradingSession.LONDON: 1.2,
        TradingSession.NY_OVERLAP: 0.7,
        TradingSession.NY_AFTERNOON: 1.0,
        TradingSession.OFF_HOURS: 2.0,
    },
    "NZDUSD": {
        TradingSession.ASIAN: 1.8,
        TradingSession.LONDON: 1.5,
        TradingSession.NY_OVERLAP: 0.9,
        TradingSession.NY_AFTERNOON: 1.2,
        TradingSession.OFF_HOURS: 2.5,
    },
    "EURGBP": {
        TradingSession.ASIAN: 2.0,
        TradingSession.LONDON: 1.0,
        TradingSession.NY_OVERLAP: 0.8,
        TradingSession.NY_AFTERNOON: 1.2,
        TradingSession.OFF_HOURS: 2.5,
    },
    "EURJPY": {
        TradingSession.ASIAN: 2.0,
        TradingSession.LONDON: 1.2,
        TradingSession.NY_OVERLAP: 0.8,
        TradingSession.NY_AFTERNOON: 1.2,
        TradingSession.OFF_HOURS: 2.5,
    },
    "GBPJPY": {
        TradingSession.ASIAN: 3.0,
        TradingSession.LONDON: 2.0,
        TradingSession.NY_OVERLAP: 1.2,
        TradingSession.NY_AFTERNOON: 2.0,
        TradingSession.OFF_HOURS: 3.5,
    },
}

# Fallback spread (pips) for pairs not in SPREAD_TABLE
DEFAULT_SPREAD_PIPS = 1.5

# JPY pairs use 0.01 pip size, everything else 0.0001
_JPY_PIP_SIZE = 0.01
_STD_PIP_SIZE = 0.0001


@dataclass
class ExecutionConfig:
    spread_pips: float = 1.0  # legacy fallback, unused when session-aware
    slippage_pips: float = 0.5
    latency_ms: int = 100
    commission_per_lot: float = 7.0
    default_lot_size: float = 0.1
    # Volatility multiplier cap: spreads can widen up to this factor
    # during high-ATR periods.  1.0 = no widening.
    vol_multiplier_cap: float = 5.0
    # Base ATR (pips) used as the reference point for vol scaling.
    # When vol_atr_pips equals this, multiplier is 1.0.
    vol_baseline_atr_pips: float = 10.0


@dataclass
class ExecutionResult:
    executed_price: float
    slippage: float
    spread_cost: float
    commission: float
    total_cost: float
    timestamp: pd.Timestamp
    # Session-aware breakdown (populated by session-aware execution)
    session: Optional[str] = None
    base_spread_pips: Optional[float] = None
    vol_multiplier: Optional[float] = None
    pair: Optional[str] = None


class ExecutionSimulator:
    """Backtest execution model with session-aware spreads.

    When *timestamp* is supplied to ``execute_long`` / ``execute_short``
    the simulator looks up the base spread for *pair* × session from
    :data:`SPREAD_TABLE` and optionally scales it by an ATR-based
    volatility multiplier.

    Parameters
    ----------
    config:
        :class:`ExecutionConfig` instance.  If *None* a default is used.
    """

    def __init__(self, config: Optional[ExecutionConfig] = None):
        self.config = config if config is not None else ExecutionConfig()

    # -- public API --------------------------------------------------------

    def execute_long(
        self,
        signal_price: float,
        timestamp: pd.Timestamp,
        lot_size: Optional[float] = None,
        pair: str = "EURUSD",
        vol_atr_pips: Optional[float] = None,
    ) -> ExecutionResult:
        return self._execute(
            signal_price, timestamp, lot_size, pair, is_long=True,
            vol_atr_pips=vol_atr_pips,
        )

    def execute_short(
        self,
        signal_price: float,
        timestamp: pd.Timestamp,
        lot_size: Optional[float] = None,
        pair: str = "EURUSD",
        vol_atr_pips: Optional[float] = None,
    ) -> ExecutionResult:
        return self._execute(
            signal_price, timestamp, lot_size, pair, is_long=False,
            vol_atr_pips=vol_atr_pips,
        )

    # -- internals ---------------------------------------------------------

    def _execute(
        self,
        signal_price: float,
        timestamp: pd.Timestamp,
        lot_size: Optional[float],
        pair: str,
        is_long: bool,
        vol_atr_pips: Optional[float] = None,
    ) -> ExecutionResult:
        if lot_size is None:
            lot_size = self.config.default_lot_size

        session = get_trading_session(timestamp)
        base_spread_pips = self._lookup_base_spread(pair, session)
        vol_mult = self._compute_vol_multiplier(vol_atr_pips)
        effective_spread_pips = base_spread_pips * vol_mult

        pip_size = _JPY_PIP_SIZE if "JPY" in pair else _STD_PIP_SIZE
        spread_cost = effective_spread_pips * pip_size
        slippage = self._calculate_slippage()

        if is_long:
            executed_price = signal_price + spread_cost + slippage
        else:
            executed_price = signal_price - spread_cost - slippage

        commission = self.config.commission_per_lot * lot_size
        total_cost = (spread_cost + slippage) * lot_size + commission

        return ExecutionResult(
            executed_price=executed_price,
            slippage=slippage,
            spread_cost=spread_cost,
            commission=commission,
            total_cost=total_cost,
            timestamp=timestamp,
            session=session.value,
            base_spread_pips=base_spread_pips,
            vol_multiplier=vol_mult,
            pair=pair,
        )

    # -- spread helpers ----------------------------------------------------

    @staticmethod
    def _lookup_base_spread(pair: str, session: TradingSession) -> float:
        """Return base spread in pips for *pair* during *session*."""
        pair_table = SPREAD_TABLE.get(pair)
        if pair_table is not None:
            return pair_table.get(session, DEFAULT_SPREAD_PIPS)
        return DEFAULT_SPREAD_PIPS

    def _compute_vol_multiplier(self, vol_atr_pips: Optional[float]) -> float:
        """Return a volatility multiplier capped at ``vol_multiplier_cap``.

        *vol_atr_pips* is the current ATR(14) in pips.  When *None*
        the multiplier defaults to 1.0 (no volatility scaling).

        Formula: ``min(cap, max(1.0, vol_atr_pips / baseline_atr_pips))``
        """
        if vol_atr_pips is None:
            return 1.0
        baseline = self.config.vol_baseline_atr_pips
        if baseline <= 0:
            return 1.0
        raw = vol_atr_pips / baseline
        return min(self.config.vol_multiplier_cap, max(1.0, raw))

    # -- legacy helpers ----------------------------------------------------

    def _calculate_spread(self, pair: str) -> float:
        """Backward-compatible spread lookup (pips → price distance).

        Uses the current UTC session to look up the base spread.
        """
        import pandas as pd
        now = pd.Timestamp.now(tz="UTC")
        session = get_trading_session(now)
        base_pips = ExecutionSimulator._lookup_base_spread(pair, session)
        pip_size = _STD_PIP_SIZE if "JPY" not in pair else _JPY_PIP_SIZE
        return base_pips * pip_size

    def _calculate_slippage(self) -> float:
        return np.random.uniform(0, self.config.slippage_pips) * _STD_PIP_SIZE

    def calculate_pip_value(self, pair: str, lot_size: float) -> float:
        pip_size = _STD_PIP_SIZE if "JPY" not in pair else _JPY_PIP_SIZE
        return lot_size * 100000 * pip_size
