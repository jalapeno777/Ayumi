from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Generator, Optional, cast

from backtest.engine import MarketState, StrategySignal, determine_session


@dataclass(frozen=True)
class WindowMetrics:
    window_index: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    trade_count: int
    total_pnl: float
    passed_go_nogo: bool


@dataclass(frozen=True)
class AggregatedMetrics:
    mean_win_rate: float
    std_win_rate: float
    mean_profit_factor: float
    std_profit_factor: float
    mean_max_drawdown: float
    std_max_drawdown: float
    mean_sharpe_ratio: float
    std_sharpe_ratio: float
    mean_trade_count: float
    std_trade_count: float
    mean_total_pnl: float
    std_total_pnl: float
    windows_passed: int
    total_windows: int


@dataclass
class WalkForwardResults:
    per_window: list[WindowMetrics] = field(default_factory=list)
    aggregated: Optional[AggregatedMetrics] = None
    go_nogo: bool = False


@dataclass
class WalkForwardValidator:
    data: list[Any]
    n_windows: int = 3
    train_ratio: float = 0.7
    val_ratio: float = 0.15
    overlap_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.n_windows < 3:
            raise ValueError(f"n_windows must be >= 3, got {self.n_windows}")
        if self.train_ratio <= 0 or self.train_ratio >= 1:
            raise ValueError(f"train_ratio must be in (0, 1), got {self.train_ratio}")
        if self.val_ratio <= 0 or self.val_ratio >= 1:
            raise ValueError(f"val_ratio must be in (0, 1), got {self.val_ratio}")
        if self.train_ratio + self.val_ratio >= 1:
            raise ValueError("train_ratio + val_ratio must be < 1")
        if self.overlap_ratio < 0 or self.overlap_ratio >= 1:
            raise ValueError(
                f"overlap_ratio must be in [0, 1), got {self.overlap_ratio}"
            )

    def split(
        self, data: Optional[list[Any]] = None
    ) -> Generator[tuple[list[Any], list[Any], list[Any]], None, None]:
        source = data if data is not None else self.data
        n = len(source)
        if n == 0:
            return

        test_ratio = 1.0 - self.train_ratio - self.val_ratio
        full_window_size = int(n / self.n_windows)
        if full_window_size == 0:
            raise ValueError(
                f"Data length ({n}) is too small for {self.n_windows} windows"
            )

        train_size = int(full_window_size * self.train_ratio)
        val_size = int(full_window_size * self.val_ratio)
        test_size = int(full_window_size * test_ratio)
        window_size = train_size + val_size + test_size

        if window_size == 0:
            return

        overlap_size = int(window_size * self.overlap_ratio)
        step = max(window_size - overlap_size, 1)

        for i in range(self.n_windows):
            start = i * step
            end = start + window_size
            if end > n:
                end = n
                start = end - window_size
                if start < 0:
                    start = 0

            window = source[start:end]
            if len(window) < window_size:
                actual_window_size = len(window)
                actual_train = int(actual_window_size * self.train_ratio)
                actual_val = int(actual_window_size * self.val_ratio)
            else:
                actual_train = train_size
                actual_val = val_size

            train = window[:actual_train]
            val = window[actual_train : actual_train + actual_val]
            test = window[actual_train + actual_val :]

            if not train or not val or not test:
                continue

            yield train, val, test


def _compute_metrics(
    window_index: int,
    trades: list[dict[str, Any]],
) -> WindowMetrics:
    if not trades:
        return WindowMetrics(
            window_index=window_index,
            win_rate=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            trade_count=0,
            total_pnl=0.0,
            passed_go_nogo=False,
        )

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_win = sum(wins)
    total_loss = abs(sum(losses))

    win_rate = len(wins) / len(pnls)
    profit_factor = total_win / total_loss if total_loss > 0 else float("inf")
    total_pnl = sum(pnls)
    trade_count = len(pnls)

    running_max = 0.0
    max_dd = 0.0
    cumulative = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > running_max:
            running_max = cumulative
        dd = running_max - cumulative
        if dd > max_dd:
            max_dd = dd

    if trade_count < 2:
        sharpe_ratio = 0.0
    else:
        mean_pnl = total_pnl / trade_count
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (trade_count - 1)
        std_pnl = math.sqrt(variance) if variance > 0 else 0.0
        sharpe_ratio = (mean_pnl / std_pnl) * math.sqrt(252) if std_pnl > 0 else 0.0

    passed = win_rate > 0.55 and profit_factor > 1.0 and total_pnl > 0 and max_dd < 0.10

    return WindowMetrics(
        window_index=window_index,
        win_rate=win_rate,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe_ratio,
        trade_count=trade_count,
        total_pnl=total_pnl,
        passed_go_nogo=passed,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def run_strategy(
    strategy_fn: Callable[..., list[dict[str, Any]]],
    data: list[Any],
    n_windows: int = 3,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    overlap_ratio: float = 0.2,
    **kwargs: Any,
) -> WalkForwardResults:
    validator = WalkForwardValidator(
        data=data,
        n_windows=n_windows,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        overlap_ratio=overlap_ratio,
    )

    per_window: list[WindowMetrics] = []
    for idx, (train, val, test) in enumerate(validator.split(data)):
        evaluate_method = cast(Callable[[MarketState], Optional[StrategySignal]], getattr(strategy_fn, 'evaluate', None))
        if callable(evaluate_method):
            accumulated_trades: list[dict[str, Any]] = []
            accumulated_train: list[Any] = []
            for bar in train:
                accumulated_train.append(bar)

            accumulated_val: list[Any] = list(accumulated_train)
            for bar in val:
                accumulated_val.append(bar)

            accumulated_test: list[Any] = list(accumulated_val)
            for bar in test:
                accumulated_test.append(bar)
                state = MarketState(
                    bars=list(accumulated_test),
                    current_session=determine_session(bar.time),
                )
                signal = evaluate_method(state)
                if signal:
                    accumulated_trades.append({
                        "pnl": signal.confidence * 100,
                        "direction": signal.direction.value,
                    })

            trades = accumulated_trades
        else:
            trades = strategy_fn(train, val, test, **kwargs)
        metrics = _compute_metrics(idx, trades)
        per_window.append(metrics)

    aggregated = None
    if per_window:
        wr_values = [m.win_rate for m in per_window]
        pf_values = [m.profit_factor for m in per_window]
        dd_values = [m.max_drawdown for m in per_window]
        sr_values = [m.sharpe_ratio for m in per_window]
        tc_values = [float(m.trade_count) for m in per_window]
        pnl_values = [m.total_pnl for m in per_window]

        mean_wr = _mean(wr_values)
        mean_pf = _mean(pf_values)
        mean_dd = _mean(dd_values)
        mean_sr = _mean(sr_values)
        mean_tc = _mean(tc_values)
        mean_pnl = _mean(pnl_values)

        aggregated = AggregatedMetrics(
            mean_win_rate=mean_wr,
            std_win_rate=_std(wr_values, mean_wr),
            mean_profit_factor=mean_pf,
            std_profit_factor=_std(pf_values, mean_pf),
            mean_max_drawdown=mean_dd,
            std_max_drawdown=_std(dd_values, mean_dd),
            mean_sharpe_ratio=mean_sr,
            std_sharpe_ratio=_std(sr_values, mean_sr),
            mean_trade_count=mean_tc,
            std_trade_count=_std(tc_values, mean_tc),
            mean_total_pnl=mean_pnl,
            std_total_pnl=_std(pnl_values, mean_pnl),
            windows_passed=sum(1 for m in per_window if m.passed_go_nogo),
            total_windows=len(per_window),
        )

    windows_passed = sum(1 for m in per_window if m.passed_go_nogo)
    total = len(per_window)
    go_nogo = total >= 3 and windows_passed >= 2

    return WalkForwardResults(
        per_window=per_window,
        aggregated=aggregated,
        go_nogo=go_nogo,
    )


def go_nogo_criteria(results: WalkForwardResults) -> bool:
    if len(results.per_window) < 3:
        return False
    passed = sum(1 for m in results.per_window if m.passed_go_nogo)
    return passed >= 2


def comparison_report(
    results_a: WalkForwardResults,
    results_b: WalkForwardResults,
) -> str:
    def fmt(value: float, precision: int = 4) -> str:
        return f"{value:.{precision}f}"

    def pct(value: float, precision: int = 2) -> str:
        return f"{value * 100:.{precision}f}%"

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("WALK-FORWARD COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")

    agg_a = results_a.aggregated
    agg_b = results_b.aggregated

    if agg_a is None and agg_b is None:
        lines.append("No results to compare.")
        return "\n".join(lines)

    lines.append(f"{'Metric':<25} {'Strategy A':>18} {'Strategy B':>18} {'Delta':>14}")
    lines.append("-" * 80)

    metrics_to_compare = [
        ("Win Rate", "mean_win_rate", True),
        ("Profit Factor", "mean_profit_factor", False),
        ("Max Drawdown", "mean_max_drawdown", True),
        ("Sharpe Ratio", "mean_sharpe_ratio", False),
        ("Trade Count", "mean_trade_count", False),
        ("Total PnL", "mean_total_pnl", False),
    ]

    for label, attr_name, is_pct in metrics_to_compare:
        val_a = getattr(agg_a, attr_name, 0.0) if agg_a else 0.0
        val_b = getattr(agg_b, attr_name, 0.0) if agg_b else 0.0
        delta = val_a - val_b

        str_a = pct(val_a) if is_pct else fmt(val_a)
        str_b = pct(val_b) if is_pct else fmt(val_b)
        str_delta = pct(delta) if is_pct else fmt(delta)

        lines.append(f"{label:<25} {str_a:>18} {str_b:>18} {str_delta:>14}")

    lines.append("-" * 80)
    lines.append("")

    passed_a = sum(1 for m in results_a.per_window if m.passed_go_nogo)
    passed_b = sum(1 for m in results_b.per_window if m.passed_go_nogo)
    total_a = len(results_a.per_window)
    total_b = len(results_b.per_window)

    lines.append(
        f"Strategy A: {passed_a}/{total_a} windows passed GO/NO-GO  -> {'GO' if results_a.go_nogo else 'NO-GO'}"
    )
    lines.append(
        f"Strategy B: {passed_b}/{total_b} windows passed GO/NO-GO  -> {'GO' if results_b.go_nogo else 'NO-GO'}"
    )
    lines.append("")

    if agg_a:
        lines.append("Strategy A Per-Window Details:")
        lines.append("-" * 80)
        lines.append(
            f"{'Window':<8} {'WR':>8} {'PF':>8} {'MaxDD':>10} {'Sharpe':>10} {'Trades':>8} {'PnL':>12} {'GO?':>6}"
        )
        for m in results_a.per_window:
            lines.append(
                f"{m.window_index:<8} {pct(m.win_rate):>8} {fmt(m.profit_factor):>8} "
                f"{pct(m.max_drawdown):>10} {fmt(m.sharpe_ratio):>10} {m.trade_count:>8} "
                f"{fmt(m.total_pnl):>12} {'YES' if m.passed_go_nogo else 'NO':>6}"
            )
        lines.append("")

    if agg_b:
        lines.append("Strategy B Per-Window Details:")
        lines.append("-" * 80)
        lines.append(
            f"{'Window':<8} {'WR':>8} {'PF':>8} {'MaxDD':>10} {'Sharpe':>10} {'Trades':>8} {'PnL':>12} {'GO?':>6}"
        )
        for m in results_b.per_window:
            lines.append(
                f"{m.window_index:<8} {pct(m.win_rate):>8} {fmt(m.profit_factor):>8} "
                f"{pct(m.max_drawdown):>10} {fmt(m.sharpe_ratio):>10} {m.trade_count:>8} "
                f"{fmt(m.total_pnl):>12} {'YES' if m.passed_go_nogo else 'NO':>6}"
            )
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)
