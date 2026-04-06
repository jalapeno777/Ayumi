"""Run parameter sweeps on the 4 implemented strategies using M15 data.

This script runs systematic parameter optimization across:
1. MomentumBreakoutStrategy
2. CommodityTrendStrategy
3. GridStrategy
4. PairsSignalGenerator (Stat Arb)

Metrics collected: WR, Sharpe, max DD, total return, trade count, profit factor.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src" / "forex-bot"))
sys.path.insert(0, str(project_root / "src"))

from backtest import BacktestConfig, CsvDataLoader
from backtest.parameter_sweep import ParameterGrid, SweepRunner
from backtest.strategies import (
    MomentumBreakoutStrategy,
    CommodityTrendStrategy,
)
from strategies.grid import GridStrategyAdapter
from strategies.grid.config import GridConfig


SYMBOL = "EURUSD"
TIMEFRAME = "M15"
DATA_DIR = project_root / "data" / "forex" / "historical"
OUTPUT_DIR = project_root / "reports" / "parameter_sweeps"
MAX_WORKERS = None


def load_m15_data(symbol: str, timeframe: str):
    csv_path = DATA_DIR / f"{symbol}_{timeframe}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Data file not found: {csv_path}")
    loader = CsvDataLoader()
    bars = loader.load(str(csv_path))
    print(f"Loaded {len(bars)} bars from {csv_path}")
    print(f"Date range: {bars[0].time} to {bars[-1].time}")
    return bars


def create_momentum_breakout_grid() -> ParameterGrid:
    param_space = {
        "fast_period": [5, 8, 9],
        "slow_period": [15, 21, 25],
        "adx_period": [14],
        "adx_threshold": [20.0, 25.0],
        "atr_multiplier": [1.5, 2.0],
    }
    return ParameterGrid(param_space)


def create_commodity_trend_grid() -> ParameterGrid:
    param_space = {
        "fast_ema_period": [15, 20],
        "slow_ema_period": [40, 50],
        "adx_period": [14],
        "adx_threshold": [20.0, 25.0],
        "atr_multiplier": [1.5, 1.75],
        "risk_reward_ratio": [1.5, 2.0],
    }
    return ParameterGrid(param_space)


def create_grid_strategy_grid() -> ParameterGrid:
    param_space = {
        "symbol": ["EURUSD"],
        "grid_spacing": [0.0010, 0.0015],
        "levels_per_side": [3, 5],
        "take_profit_pips": [8.0, 10.0],
    }
    return ParameterGrid(param_space)


def momentum_breakout_factory(point) -> MomentumBreakoutStrategy:
    return MomentumBreakoutStrategy(
        fast_period=point.params.get("fast_period", 9),
        slow_period=point.params.get("slow_period", 21),
        adx_period=point.params.get("adx_period", 14),
        adx_threshold=point.params.get("adx_threshold", 25.0),
        atr_multiplier=point.params.get("atr_multiplier", 2.0),
    )


def commodity_trend_factory(point) -> CommodityTrendStrategy:
    return CommodityTrendStrategy(
        fast_ema_period=point.params.get("fast_ema_period", 20),
        slow_ema_period=point.params.get("slow_ema_period", 50),
        adx_period=point.params.get("adx_period", 14),
        adx_threshold=point.params.get("adx_threshold", 25.0),
        atr_multiplier=point.params.get("atr_multiplier", 1.75),
        risk_reward_ratio=point.params.get("risk_reward_ratio", 2.0),
    )


def grid_strategy_factory(point) -> GridStrategyAdapter:
    symbol = point.params.get("symbol", "EURUSD")
    spacing_map = {
        "EURUSD": 0.0015,
        "GBPUSD": 0.0015,
        "USDJPY": 0.15,
    }
    pip_map = {
        "EURUSD": 0.0001,
        "GBPUSD": 0.0001,
        "USDJPY": 0.01,
    }
    grid_config = GridConfig(
        symbol=symbol,
        grid_spacing=point.params.get("grid_spacing", spacing_map.get(symbol, 0.0015)),
        levels_per_side=point.params.get("levels_per_side", 5),
        base_lot=0.1,
        lot_sizes=[0.10, 0.08, 0.06, 0.05, 0.04],
        take_profit_pips=point.params.get("take_profit_pips", 10.0),
        pip_value=pip_map.get(symbol, 0.0001),
        contract_size=100000.0,
        spread=0.00005,
    )
    return GridStrategyAdapter(grid_config)


def run_sweep(
    name: str,
    bars,
    config: BacktestConfig,
    grid: ParameterGrid,
    factory,
    max_workers: int = MAX_WORKERS,
) -> Dict[str, Any]:
    print(f"\n{'='*60}")
    print(f"Running sweep: {name}")
    print(f"Grid size: {len(grid)} configurations")
    print(f"{'='*60}")

    runner = SweepRunner(config, bars, factory, max_workers=max_workers)
    result = runner.run(grid)

    print(f"Completed {len(result)} successful runs out of {len(grid)} total")

    top_sharpe = result.top_n(5, metric="sharpe_ratio")
    top_wr = result.top_n(5, metric="win_rate")
    top_pf = result.top_n(5, metric="profit_factor")

    print("\nTop 5 by Sharpe Ratio:")
    for i, row in enumerate(top_sharpe, 1):
        print(f"  {i}. WR={row.win_rate:.1f}%, Sharpe={row.sharpe_ratio:.3f}, "
              f"PF={row.profit_factor:.2f}, MaxDD={row.max_dd:.2f}%, "
              f"Trades={row.trade_count}, Return={row.total_return:.2f}%")
        print(f"     Params: {row.params}")

    return {
        "strategy": name,
        "total_configs": len(grid),
        "successful_runs": len(result),
        "top_by_sharpe": [
            {
                "params": row.params,
                "win_rate": row.win_rate,
                "sharpe_ratio": row.sharpe_ratio,
                "profit_factor": row.profit_factor,
                "max_dd": row.max_dd,
                "total_return": row.total_return,
                "trade_count": row.trade_count,
            }
            for row in top_sharpe
        ],
        "top_by_win_rate": [
            {
                "params": row.params,
                "win_rate": row.win_rate,
                "sharpe_ratio": row.sharpe_ratio,
                "profit_factor": row.profit_factor,
                "max_dd": row.max_dd,
                "total_return": row.total_return,
                "trade_count": row.trade_count,
            }
            for row in top_wr
        ],
        "top_by_profit_factor": [
            {
                "params": row.params,
                "win_rate": row.win_rate,
                "sharpe_ratio": row.sharpe_ratio,
                "profit_factor": row.profit_factor,
                "max_dd": row.max_dd,
                "total_return": row.total_return,
                "trade_count": row.trade_count,
            }
            for row in top_pf
        ],
    }


MAX_BARS = 10000


def main():
    print("=" * 70)
    print("ML Parameter Sweeps on Implemented Strategies")
    print(f"Symbol: {SYMBOL} | Timeframe: {TIMEFRAME}")
    print(f"Max bars: {MAX_BARS}")
    print("=" * 70)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    bars = load_m15_data(SYMBOL, TIMEFRAME)
    bars = bars[:MAX_BARS]
    print(f"Using {len(bars)} bars for sweeps")

    config = BacktestConfig(
        starting_balance=10000.0,
        risk_per_trade_pct=0.01,
        max_daily_drawdown_pct=0.05,
        max_total_drawdown_pct=0.10,
        spread_pips=0.5,
        commission_per_lot=3.5,
        leverage=100,
        min_confidence=0.45,
        min_bars_before_signal=30,
        max_open_trades=1,
    )

    results = []

    momentum_result = run_sweep(
        "MomentumBreakoutStrategy",
        bars,
        config,
        create_momentum_breakout_grid(),
        momentum_breakout_factory,
    )
    results.append(momentum_result)

    # commodity_result = run_sweep(
    #     "CommodityTrendStrategy",
    #     bars,
    #     config,
    #     create_commodity_trend_grid(),
    #     commodity_trend_factory,
    # )
    # results.append(commodity_result)

    # grid_result = run_sweep(
    #     "GridStrategy",
    #     bars,
    #     config,
    #     create_grid_strategy_grid(),
    #     grid_strategy_factory,
    # )
    # results.append(grid_result)

    summary = {
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "data_bars": len(bars),
        "date_range": {
            "start": str(bars[0].time),
            "end": str(bars[-1].time),
        },
        "strategies": results,
    }

    report_path = OUTPUT_DIR / f"{SYMBOL}_{TIMEFRAME}_parameter_sweeps.json"
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n{'='*70}")
    print(f"Report saved to: {report_path}")
    print("=" * 70)

    print("\n" + "=" * 70)
    print("SUMMARY: Top Configurations by Strategy")
    print("=" * 70)
    for r in results:
        print(f"\n### {r['strategy']}")
        top = r["top_by_sharpe"][0] if r["top_by_sharpe"] else {}
        print(f"  Best Sharpe: {top.get('sharpe_ratio', 0):.3f}")
        print(f"  WR: {top.get('win_rate', 0):.1f}%, PF: {top.get('profit_factor', 0):.2f}")
        print(f"  MaxDD: {top.get('max_dd', 0):.2f}%, Return: {top.get('total_return', 0):.2f}%")
        print(f"  Trades: {top.get('trade_count', 0)}")
        print(f"  Params: {top.get('params', {})}")

    return summary


if __name__ == "__main__":
    main()