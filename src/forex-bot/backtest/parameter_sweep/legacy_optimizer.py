"""Optuna optimization for legacy strategies wrapped with ConfluenceScorer.

Follows the ttc_optimizer.py pattern, using WalkForwardObjective.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .optuna_optimizer import (
    OptimizationResult,
    SearchSpace,
    float_range,
    int_range,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DATA_DIR = _PROJECT_ROOT / "data" / "forex" / "historical"
_REPORTS_DIR = _PROJECT_ROOT / "reports" / "optuna_legacy"


# ── Strategy-specific search spaces ──────────────────────────────

def _session_range_mr_search() -> SearchSpace:
    return SearchSpace(
        min_confidence=float_range("min_confidence", 0.2, 0.6, step=0.05),
        session_range_min_pips=float_range("session_range_min_pips", 10.0, 50.0, step=5.0),
        session_range_sl_fraction=float_range("session_range_sl_fraction", 0.3, 0.9, step=0.1),
    )


def _volatility_squeeze_search() -> SearchSpace:
    return SearchSpace(
        min_confidence=float_range("min_confidence", 0.2, 0.6, step=0.05),
        bb_period=int_range("bb_period", 15, 30),
        bb_std=float_range("bb_std", 1.5, 3.0, step=0.25),
        squeeze_threshold=float_range("squeeze_threshold", 0.5, 1.5, step=0.25),
    )


def _momentum_search() -> SearchSpace:
    return SearchSpace(
        min_confidence=float_range("min_confidence", 0.2, 0.6, step=0.05),
        ema_fast=int_range("ema_fast", 5, 15),
        ema_slow=int_range("ema_slow", 20, 60),
        rsi_period=int_range("rsi_period", 10, 20),
    )


def _killzone_momentum_search() -> SearchSpace:
    return SearchSpace(
        min_confidence=float_range("min_confidence", 0.2, 0.6, step=0.05),
        kill_zone_start_hour=int_range("kill_zone_start_hour", 0, 23),
        kill_zone_end_hour=int_range("kill_zone_end_hour", 0, 23),
    )


_SEARCH_SPACES: dict[str, callable] = {
    "session_range_mr": _session_range_mr_search,
    "volatility_squeeze": _volatility_squeeze_search,
    "momentum": _momentum_search,
    "killzone_momentum": _killzone_momentum_search,
}


# ── Strategy factory ─────────────────────────────────────────────

def legacy_strategy_factory(
    strategy_name: str,
    params: dict[str, Any],
    symbol: str = "EURUSD",
    timeframe: str = "M15",
):
    """Create a confluence-wrapped legacy strategy with given params."""
    from backtest.strategies.confluence_wrapped_strategy import (
        ConfluenceWrappedStrategy,
        ConfluenceWrapperConfig,
    )

    inner = _create_inner_strategy(strategy_name, params, symbol, timeframe)
    wrapper_config = ConfluenceWrapperConfig(
        min_confidence=params.get("min_confidence", 0.3),
        use_gates=True,
    )
    return ConfluenceWrappedStrategy(inner, symbol=symbol, timeframe=timeframe, config=wrapper_config)


def _create_inner_strategy(
    strategy_name: str,
    params: dict[str, Any],
    symbol: str,
    timeframe: str,
) -> Any:
    if strategy_name == "session_range_mr":
        from strategies.session_range_mean_reversion import (
            SessionRangeMeanReversionStrategy,
            SessionRangeMRConfig,
        )
        config = SessionRangeMRConfig(
            session_range_min_pips=params.get("session_range_min_pips", 25.0),
            session_range_sl_fraction=params.get("session_range_sl_fraction", 0.6),
        )
        return SessionRangeMeanReversionStrategy(config=config)

    elif strategy_name == "volatility_squeeze":
        from strategies.volatility_squeeze import (
            VolatilitySqueezeStrategy,
            VolatilitySqueezeConfig,
        )
        config = VolatilitySqueezeConfig(
            bb_period=params.get("bb_period", 20),
            bb_std_dev=params.get("bb_std", 2.0),
            squeeze_threshold=params.get("squeeze_threshold", 0.0),
        )
        return VolatilitySqueezeStrategy(config=config)

    elif strategy_name == "momentum":
        from strategies.momentum import (
            MATrendFollowingStrategy,
            MomentumConfig,
        )
        momentum_config = MomentumConfig(
            rsi_period=params.get("rsi_period", 14),
        )
        return MATrendFollowingStrategy(
            fast_period=params.get("ema_fast", 8),
            slow_period=params.get("ema_slow", 21),
            momentum_config=momentum_config,
        )

    elif strategy_name == "killzone_momentum":
        from strategies.killzone_momentum import (
            KillzoneMomentumStrategy,
            KillzoneMomentumConfig,
        )
        config = KillzoneMomentumConfig()
        return KillzoneMomentumStrategy(config=config)

    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")


# ── Data loading ─────────────────────────────────────────────────

def load_bars(pair: str, timeframe: str = "M15") -> list:
    from datetime import datetime as _dt
    from backtest.engine import Bar

    csv_path = _DATA_DIR / f"{pair.upper()}_{timeframe}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No data for {pair} {timeframe}: {csv_path}")

    bars = []
    with open(csv_path) as f:
        f.readline()
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 6:
                continue
            try:
                date_str = parts[0].strip()
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                    try:
                        bar_time = _dt.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                bars.append(Bar(
                    time=bar_time,
                    open=float(parts[1]),
                    high=float(parts[2]),
                    low=float(parts[3]),
                    close=float(parts[4]),
                    volume=float(parts[5]),
                ))
            except (ValueError, IndexError):
                continue
    logger.info("Loaded %d %s bars for %s", len(bars), timeframe, pair)
    return bars


# ── Optuna runner ────────────────────────────────────────────────

def run_legacy_optuna(
    strategy_name: str,
    pair: str = "EURUSD",
    timeframe: str = "M15",
    n_trials: int = 100,
    n_windows: int = 5,
    seed: int = 42,
    composite_weights: dict[str, float] | None = None,
    min_trades: int = 2,
) -> OptimizationResult:
    """Run Optuna optimization for a legacy strategy."""
    import optuna
    from optuna.samplers import TPESampler
    from .optuna_optimizer import WalkForwardObjective

    if strategy_name not in _SEARCH_SPACES:
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {list(_SEARCH_SPACES.keys())}")

    bars = load_bars(pair, timeframe)
    search_space = _SEARCH_SPACES[strategy_name]()

    def factory(_params):
        return legacy_strategy_factory(strategy_name, _params, symbol=pair, timeframe=timeframe)

    class LegacyObjective(WalkForwardObjective):
        def __init__(self, *args, min_trades=2, **kwargs):
            super().__init__(*args, **kwargs)
            self._min_trades = min_trades

        def __call__(self, trial):
            from backtest.walk_forward_runner import run_strategy_walk_forward
            params = self._search_space.suggest(trial)
            strategy = self._strategy_factory(params)
            try:
                wf_result = run_strategy_walk_forward(
                    bars=self._bars,
                    strategy_factory=lambda: strategy,
                    pair=self._pair,
                    n_windows=self._n_windows,
                    train_ratio=self._train_ratio,
                    val_ratio=self._val_ratio,
                    overlap_ratio=self._overlap_ratio,
                    initial_balance=self._initial_balance,
                    spread_pips=self._spread_pips,
                    commission_per_lot=self._commission_per_lot,
                )
            except Exception as exc:
                logger.warning("WF failed trial %d: %s", trial.number, exc)
                raise optuna.TrialPruned() from exc

            self._results_by_trial[trial.number] = wf_result
            self._params_by_trial[trial.number] = params
            agg = wf_result.aggregated
            if agg is None:
                raise optuna.TrialPruned()
            if agg.mean_trade_count < self._min_trades:
                raise optuna.TrialPruned()

            score = self._composite_score(agg)
            trial.set_user_attr("win_rate", agg.mean_win_rate)
            trial.set_user_attr("profit_factor", agg.mean_profit_factor)
            trial.set_user_attr("max_drawdown", agg.mean_max_drawdown)
            trial.set_user_attr("sharpe_ratio", agg.mean_sharpe_ratio)
            trial.set_user_attr("trade_count", agg.mean_trade_count)
            trial.set_user_attr("go_nogo", wf_result.go_nogo)

            if not wf_result.go_nogo:
                score -= 1.0
            return score

    objective = LegacyObjective(
        bars=bars, strategy_factory=factory, pair=pair,
        search_space=search_space, n_windows=n_windows,
        composite_weights=composite_weights, min_trades=min_trades,
    )

    sampler = TPESampler(seed=seed)
    study = optuna.create_study(sampler=sampler, direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
    if not completed:
        return OptimizationResult(
            best_params={}, best_value=float("-inf"),
            n_trials=len(study.trials), go_nogo=False,
            study_summary={"n_trials": len(study.trials), "n_complete": 0, "n_pruned": len(study.trials)},
        )

    best_trial = study.best_trial
    best_wf = objective.get_result(best_trial.number)

    result = OptimizationResult(
        best_params=best_trial.params,
        best_value=best_trial.value if best_trial.value is not None else float("-inf"),
        best_walk_forward=best_wf,
        n_trials=len(study.trials),
        go_nogo=best_wf.go_nogo if best_wf else False,
        study_summary={
            "n_trials": len(study.trials),
            "n_complete": len(completed),
            "n_pruned": len([t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]),
            "best_score": best_trial.value,
            "sampler": type(sampler).__name__,
        },
    )

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    out_path = _REPORTS_DIR / f"{strategy_name}_{pair}_{timeframe}_{timestamp}.json"
    report = {
        "strategy": strategy_name, "pair": pair, "timeframe": timeframe,
        "n_trials": result.n_trials, "best_score": result.best_value,
        "go_nogo": result.go_nogo, "best_params": result.best_params,
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info("Results saved to %s", out_path)
    return result
