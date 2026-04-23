from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluateResult:
    passed: bool
    details: str = ""


@dataclass(frozen=True)
class PerWindowCriteria:
    min_trades: int = 5
    win_rate: float = 0.55
    profit_factor: float = 1.3
    max_drawdown: float = 0.10

    def evaluate(
        self,
        trade_count: int,
        win_rate: float,
        profit_factor: float,
        total_pnl: float,
        max_drawdown: float,
    ) -> EvaluateResult:
        failures: list[str] = []
        if trade_count < self.min_trades:
            failures.append(f"trade_count={trade_count} < min_trades={self.min_trades}")
        if win_rate < self.win_rate:
            failures.append(f"win_rate={win_rate:.4f} < threshold={self.win_rate:.4f}")
        if profit_factor < self.profit_factor:
            failures.append(
                f"profit_factor={profit_factor:.4f} < threshold={self.profit_factor:.4f}"
            )
        if max_drawdown > self.max_drawdown:
            failures.append(
                f"max_drawdown={max_drawdown:.4f} > threshold={self.max_drawdown:.4f}"
            )

        passed = len(failures) == 0
        detail = "; ".join(failures) if failures else "all criteria met"
        return EvaluateResult(passed=passed, details=detail)


@dataclass(frozen=True)
class AggregateCriteria:
    min_total_trades: int = 50
    min_windows_passed: int = 3
    min_total_windows: int = 3

    def evaluate(
        self,
        total_trades: int,
        windows_passed: int,
        total_windows: int,
    ) -> EvaluateResult:
        failures: list[str] = []
        if total_trades < self.min_total_trades:
            failures.append(
                f"total_trades={total_trades} < min={self.min_total_trades}"
            )
        if windows_passed < self.min_windows_passed:
            failures.append(
                f"windows_passed={windows_passed} < min={self.min_windows_passed}"
            )
        if total_windows < self.min_total_windows:
            failures.append(
                f"total_windows={total_windows} < min={self.min_total_windows}"
            )

        passed = len(failures) == 0
        detail = "; ".join(failures) if failures else "all criteria met"
        return EvaluateResult(passed=passed, details=detail)
