from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from ..engine import BacktestConfig, Bar
from ..enhanced_engine import EnhancedBacktestEngine
from ..strategies import ISignalStrategy
from .grid import GridPoint, ParameterGrid
from .result import SweepResult, SweepRow

logger = logging.getLogger(__name__)

StrategyFactory = Callable[[GridPoint], ISignalStrategy]


def _worker_entry(args: tuple) -> Optional[Dict[str, Any]]:
    config_dict, bars_data, strategy_config = args
    config = BacktestConfig(**config_dict)
    bars = [Bar(**b) for b in bars_data]
    strategy = _rebuild_strategy(strategy_config)
    engine = EnhancedBacktestEngine(config=config, strategies=[strategy])
    try:
        metrics = engine.run_strategy(strategy, bars)
        return {
            "win_rate": metrics.win_rate,
            "max_dd": metrics.max_drawdown_pct,
            "total_return": metrics.total_pnl_pct,
            "sharpe_ratio": metrics.sharpe_ratio,
            "trade_count": metrics.total_trades,
            "profit_factor": metrics.profit_factor,
        }
    except Exception as exc:
        logger.warning("Backtest failed in worker: %s", exc)
        return None


def _rebuild_strategy(config: Dict[str, Any]) -> ISignalStrategy:
    cls_name = config["__class__"]
    params = {k: v for k, v in config.items() if k != "__class__"}
    from ..strategies import (
        BBStrategy,
        MACrossStrategy,
        ROCMStrategy,
        RSIStrategy,
        SRBreakoutStrategy,
        MomentumBreakoutStrategy,
        CommodityTrendStrategy,
    )
    from strategies.grid import GridStrategyAdapter
    from strategies.grid.config import GridConfig

    registry: Dict[str, type] = {
        "MACrossStrategy": MACrossStrategy,
        "BBStrategy": BBStrategy,
        "RSIStrategy": RSIStrategy,
        "SRBreakoutStrategy": SRBreakoutStrategy,
        "ROCMStrategy": ROCMStrategy,
        "MomentumBreakoutStrategy": MomentumBreakoutStrategy,
        "CommodityTrendStrategy": CommodityTrendStrategy,
        "GridStrategyAdapter": GridStrategyAdapter,
    }
    cls = registry.get(cls_name)
    if cls is None:
        raise ValueError(f"Unknown strategy class: {cls_name}")

    if cls_name == "GridStrategyAdapter":
        grid_config = GridConfig(
            symbol=params.get("symbol", "EURUSD"),
            grid_spacing=params.get("grid_spacing", 0.0015),
            levels_per_side=params.get("levels_per_side", 5),
            base_lot=params.get("base_lot", 0.1),
            lot_sizes=params.get("lot_sizes", [0.10, 0.08, 0.06, 0.05, 0.04]),
            take_profit_pips=params.get("take_profit_pips", 10.0),
            pip_value=params.get("pip_value", 0.0001),
            contract_size=params.get("contract_size", 100000.0),
            spread=params.get("spread", 0.00005),
        )
        return cls(grid_config)
    return cls(**params)


def _serialize_strategy(strategy: ISignalStrategy) -> Dict[str, Any]:
    from strategies.grid import GridStrategyAdapter

    params = {k: v for k, v in strategy.__dict__.items() if not k.startswith("_")}
    params["__class__"] = type(strategy).__name__

    if isinstance(strategy, GridStrategyAdapter):
        config = strategy.grid_config
        params["symbol"] = config.symbol
        params["grid_spacing"] = config.grid_spacing
        params["levels_per_side"] = config.levels_per_side
        params["base_lot"] = config.base_lot
        params["lot_sizes"] = config.lot_sizes
        params["take_profit_pips"] = config.take_profit_pips
        params["pip_value"] = config.pip_value
        params["contract_size"] = config.contract_size
        params["spread"] = config.spread

    return params


def _serialize_bars(bars: List[Bar]) -> List[Dict[str, Any]]:
    from dataclasses import asdict

    return [asdict(b) for b in bars]


class SweepRunner:
    def __init__(
        self,
        config: BacktestConfig,
        bars: List[Bar],
        strategy_factory: StrategyFactory,
        max_workers: Optional[int] = None,
    ):
        self._config = config
        self._bars = bars
        self._strategy_factory = strategy_factory
        self._max_workers = max_workers if max_workers is not None else os.cpu_count()

    def run(self, grid: ParameterGrid) -> SweepResult:
        rows: List[SweepRow] = []
        tasks: List[tuple] = []
        grid_points: List[GridPoint] = []

        config_dict = self._config_to_dict()
        bars_data = _serialize_bars(self._bars)

        for point in grid:
            strategy = self._strategy_factory(point)
            strategy_config = _serialize_strategy(strategy)
            tasks.append((config_dict, bars_data, strategy_config))
            grid_points.append(point)

        if self._max_workers is not None and self._max_workers > 1 and len(tasks) > 1:
            with ProcessPoolExecutor(max_workers=self._max_workers) as executor:
                future_to_idx = {
                    executor.submit(_worker_entry, task): idx
                    for idx, task in enumerate(tasks)
                }
                results: List[Optional[Dict[str, Any]]] = [None] * len(tasks)  # type: ignore[assignment]
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    results[idx] = future.result()
        else:
            results = [_worker_entry(task) for task in tasks]

        for point, result in zip(grid_points, results):
            if result is not None:
                rows.append(SweepRow(params=point.params, **result))

        return SweepResult(rows=rows)

    def _config_to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict

        return asdict(self._config)
