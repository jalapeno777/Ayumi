"""Quick backtest test for grid strategy."""

from backtest.data_loader import CsvDataLoader
from backtest.engine import BacktestConfig
from backtest.enhanced_engine import EnhancedBacktestEngine
from backtest.grid_strategy import GridDirection, GridStrategy
import pytest


@pytest.mark.xfail(reason="DEBT 6ea40384: missing forex historical CSV data files (environmental)", strict=False)
def test_grid_backtest_eurusd():
    loader = CsvDataLoader()
    bars = loader.load("data/forex/historical/EURUSD_H1.csv")
    assert len(bars) > 0, "No bars loaded"

    strategy = GridStrategy(
        pair="EURUSD",
        num_levels=10,
        grid_spacing_pips=15.0,
        max_concurrent_positions=5,
        direction=GridDirection.BOTH,
    )

    config = BacktestConfig(starting_balance=10000, risk_per_trade_pct=0.01)
    engine = EnhancedBacktestEngine(config, strategies=[strategy])
    result = engine.run_strategy(strategy, bars)

    print("\nEURUSD Results:")
    print(f"  Trades: {result.total_trades}")
    print(f"  Win Rate: {result.win_rate:.1f}%")
    print(f"  P&L: ${result.total_pnl:.2f}")
    print(f"  Max DD: {result.max_drawdown_pct:.2f}%")

    print(f"  Profit Factor: {result.profit_factor:.2f}")

    assert result.total_trades > 0, "No trades generated"


@pytest.mark.xfail(reason="DEBT 6ea40384: missing forex historical CSV data files (environmental)", strict=False)
def test_grid_backtest_gbpjpy():
    loader = CsvDataLoader()
    bars = loader.load("data/forex/historical/GBPJPY_H1.csv")
    assert len(bars) > 0, "No bars loaded"

    strategy = GridStrategy(
        pair="GBPJPY",
        num_levels=10,
        grid_spacing_pips=20.0,
        max_concurrent_positions=5,
        direction=GridDirection.BOTH,
    )

    config = BacktestConfig(starting_balance=10000, risk_per_trade_pct=0.01)
    engine = EnhancedBacktestEngine(config, strategies=[strategy])
    result = engine.run_strategy(strategy, bars)

    print("\nGBPJPY Results:")
    print(f"  Trades: {result.total_trades}")
    print(f"  Win Rate: {result.win_rate:.1f}%")
    print(f"  P&L: ${result.total_pnl:.2f}")
    print(f"  Max DD: {result.max_drawdown_pct:.2f}%")
    print(f"  Profit Factor: {result.profit_factor:.2f}")

    assert result.total_trades > 0, "No trades generated"


if __name__ == "__main__":
    test_grid_backtest_eurusd()
    test_grid_backtest_gbpjpy()
    print("\nBacktests complete!")
