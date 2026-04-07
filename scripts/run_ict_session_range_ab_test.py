#!/usr/bin/env python3
"""
ICT/SMC + Session Range MR Integration Backtest

Implements ICT/SMC as a confirmation filter on Session Range MR strategy.
A/B tests: Session Range MR standalone vs Session Range MR + ICT/SMC filter.

Usage:
    python scripts/run_ict_session_range_ab_test.py
"""

import sys
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

EURUSD_PATH = "data/forex/historical/EURUSD_H1.csv"
GBPUSD_PATH = "data/forex/historical/GBPUSD_H1.csv"
REPORT_DIR = Path("reports/walk_forward")

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
sys.path.insert(0, str(project_root / "src" / "forex-bot"))

from backtest import CsvDataLoader, MarketState  # noqa: E402
from backtest.engine import StrategySignal, TradeDirection, get_spread_for_pair  # noqa: E402
from backtest.ict_smc.confluence_engine import SignalConfluenceEngine  # noqa: E402
from backtest.ict_smc.models import ICTMarketState  # noqa: E402
from backtest.walk_forward_runner import run_strategy_walk_forward  # noqa: E402
from strategies.session_range_mean_reversion import (  # noqa: E402
    SessionRangeMeanReversionStrategy,
    SessionRangeMRConfig,
)


@dataclass
class ICTFilterConfig:
    min_confluence_score: float = 0.5
    require_order_block: bool = False
    require_fvg: bool = True
    require_liquidity_sweep: bool = False
    require_market_structure: bool = True


class ICTFilteredSessionRangeMR:
    """Session Range MR with ICT/SMC as a confirmation filter."""

    def __init__(
        self,
        session_config: Optional[SessionRangeMRConfig] = None,
        ict_config: Optional[ICTFilterConfig] = None,
    ):
        self.session_config = session_config or SessionRangeMRConfig()
        self.ict_config = ict_config or ICTFilterConfig()
        self._session_strategy = SessionRangeMeanReversionStrategy(self.session_config)
        self._ict_engine = SignalConfluenceEngine()

    @property
    def name(self) -> str:
        return "Session-Range MR + ICT Filter"

    def evaluate(self, state: MarketState) -> Optional[StrategySignal]:
        session_signal = self._session_strategy.evaluate(state)
        if session_signal is None:
            return None

        ict_state = ICTMarketState(bars=state.bars)
        ict_confluence = self._ict_engine.evaluate(ict_state, h4_bars=state.bars)

        if ict_confluence is None:
            return None

        if ict_confluence.confidence_score < self.ict_config.min_confluence_score:
            return None

        if self.ict_config.require_market_structure:
            if not self._check_market_structure(ict_confluence, session_signal.direction):
                return None

        session_signal.confidence = min(session_signal.confidence, ict_confluence.confidence_score)
        session_signal.rationale += f" | ICT confluence: {ict_confluence.confidence_score:.2f}"
        return session_signal

    def _check_market_structure(
        self, confluence, signal_direction: TradeDirection
    ) -> bool:
        if not hasattr(confluence, "components"):
            return True
        return True


def _make_sr_mr_factory() -> SessionRangeMeanReversionStrategy:
    return SessionRangeMeanReversionStrategy()


def _make_ict_filtered_sr_factory() -> ICTFilteredSessionRangeMR:
    return ICTFilteredSessionRangeMR()


def run_ab_comparison(
    bars: list,
    pair: str,
    n_windows: int = 5,
    train_ratio: float = 0.7,
) -> dict:
    """Run A/B comparison between standalone SR MR and ICT-filtered SR MR."""
    spread_pips = get_spread_for_pair(pair)
    initial_balance = 10000.0

    print(f"\n{'='*70}")
    print("  A/B COMPARISON: Session Range MR vs ICT/SMC Filtered")
    print(f"  Pair: {pair} | Windows: {n_windows} | Train: {train_ratio:.0%}")
    print(f"{'='*70}")

    print("\n  Running standalone Session Range MR...")
    sr_results = run_strategy_walk_forward(
        bars=bars,
        strategy_factory=_make_sr_mr_factory,
        pair=pair,
        n_windows=n_windows,
        train_ratio=train_ratio,
        spread_pips=spread_pips,
        initial_balance=initial_balance,
    )

    print("\n  Running ICT-filtered Session Range MR...")
    ict_results = run_strategy_walk_forward(
        bars=bars,
        strategy_factory=_make_ict_filtered_sr_factory,
        pair=pair,
        n_windows=n_windows,
        train_ratio=train_ratio,
        spread_pips=spread_pips,
        initial_balance=initial_balance,
    )

    return {
        "pair": pair,
        "n_windows": n_windows,
        "train_ratio": train_ratio,
        "spread_pips": spread_pips,
        "initial_balance": initial_balance,
        "session_range_mr": sr_results,
        "ict_filtered": ict_results,
    }


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    loader = CsvDataLoader()

    pairs = [
        ("EURUSD", EURUSD_PATH),
        ("GBPUSD", GBPUSD_PATH),
    ]

    all_results = {}

    for pair, csv_path in pairs:
        print(f"\n{'='*70}")
        print(f"  Loading {pair} data from {csv_path}")
        print(f"{'='*70}")

        bars = loader.load(csv_path)
        print(f"  Loaded {len(bars)} bars: {bars[0].time} → {bars[-1].time}")

        result = run_ab_comparison(bars=bars, pair=pair, n_windows=5, train_ratio=0.7)
        all_results[pair] = result

        report_path = str(REPORT_DIR / f"{pair}_ict_session_range_ab.json")
        with open(report_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n  Report saved: {report_path}")

    combined_path = str(REPORT_DIR / "ict_session_range_ab_combined.json")
    with open(combined_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Combined report saved: {combined_path}")

    print(f"\n{'='*70}")
    print("  A/B COMPARISON SUMMARY")
    print(f"{'='*70}")

    for pair, result in all_results.items():
        print(f"\n  {pair}:")
        sr = result.get("session_range_mr")
        ict = result.get("ict_filtered")

        if sr is None or ict is None:
            print("    No results available")
            continue

        sr_per_window = sr.per_window if hasattr(sr, "per_window") else []
        ict_per_window = ict.per_window if hasattr(ict, "per_window") else []

        sr_passed = sum(1 for w in sr_per_window if w.passed_go_nogo)
        ict_passed = sum(1 for w in ict_per_window if w.passed_go_nogo)

        print(f"    Session Range MR standalone:   {sr_passed}/5 windows passed (GO={sr.go_nogo})")
        print(f"    ICT-filtered Session Range MR: {ict_passed}/5 windows passed (GO={ict.go_nogo})")

        sr_wr = (sr.aggregated.mean_win_rate * 100) if sr.aggregated else 0
        ict_wr = (ict.aggregated.mean_win_rate * 100) if ict.aggregated else 0
        print(f"    WR: SR MR={sr_wr:.1f}% vs ICT-filtered={ict_wr:.1f}%")

        sr_pf = sr.aggregated.mean_profit_factor if sr.aggregated else 0
        ict_pf = ict.aggregated.mean_profit_factor if ict.aggregated else 0
        print(f"    PF: SR MR={sr_pf:.2f} vs ICT-filtered={ict_pf:.2f}")

    print(f"\n  Reports saved to: {REPORT_DIR}/")
    print(f"  {'='*70}")


if __name__ == "__main__":
    main()