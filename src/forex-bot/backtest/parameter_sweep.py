from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class ParameterGrid:
    param_space: dict[str, list[Any]] = field(default_factory=dict)

    def combinations(self) -> list[dict[str, Any]]:
        if not self.param_space:
            return []
        keys = list(self.param_space.keys())
        values = list(self.param_space.values())
        from itertools import product

        combos = []
        for vals in product(*values):
            combos.append(dict(zip(keys, vals)))
        return combos


@dataclass
class SweepResult:
    params: dict[str, Any]
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    trade_count: int = 0


@dataclass
class SweepRow:
    params: dict[str, Any]
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    trade_count: int = 0


class SweepRunner:
    def __init__(
        self,
        engine: Any,
        strategy_cls: type,
        param_grid: ParameterGrid,
        parallel: bool = False,
    ) -> None:
        self.engine = engine
        self.strategy_cls = strategy_cls
        self.param_grid = param_grid
        self.parallel = parallel

    def run(
        self,
    ) -> list[SweepResult]:
        results: list[SweepResult] = []
        for params in self.param_grid.combinations():
            results.append(SweepResult(params=params))
        return results

    def to_csv(self, results: list[SweepResult], path: str) -> None:
        if not results:
            return
        keys = ["params"] + list(results[0].__dataclass_fields__.keys())[1:]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for r in results:
                row = {"params": str(r.params)}
                for k in keys[1:]:
                    row[k] = getattr(r, k)
                writer.writerow(row)

    def to_json(self, results: list[SweepResult], path: str) -> None:
        data = []
        for r in results:
            d = {"params": r.params}
            for k in ["win_rate", "max_drawdown", "total_return", "sharpe_ratio", "trade_count"]:
                d[k] = getattr(r, k)
            data.append(d)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)


def to_csv(results: list[SweepResult], path: str) -> None:
    runner = SweepRunner(None, None, ParameterGrid())
    runner.to_csv(results, path)


def to_json(results: list[SweepResult], path: str) -> None:
    runner = SweepRunner(None, None, ParameterGrid())
    runner.to_json(results, path)
