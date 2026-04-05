import numpy as np
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class CointegrationResult:
    is_cointegrated: bool
    p_value: float
    hedge_ratio: float
    constant: float
    adf_statistic: float
    adf_p_value: float


@dataclass
class SpreadStats:
    mean: float
    std: float
    z_score: float
    spread: float


class CointegrationEngine:
    def __init__(self, lookback: int = 60):
        self.lookback = lookback

    def compute_hedge_ratio(
        self, prices_a: np.ndarray, prices_b: np.ndarray
    ) -> Tuple[float, float]:
        if len(prices_a) < 2 or len(prices_b) < 2:
            return 1.0, 0.0

        x = np.column_stack([np.ones(len(prices_b)), prices_b])
        try:
            coeffs = np.linalg.lstsq(x, prices_a, rcond=None)[0]
            hedge_ratio = coeffs[1]
            constant = coeffs[0]
        except np.linalg.LinAlgError:
            hedge_ratio = 1.0
            constant = 0.0

        return hedge_ratio, constant

    def compute_spread(
        self,
        prices_a: np.ndarray,
        prices_b: np.ndarray,
        hedge_ratio: Optional[float] = None,
        constant: Optional[float] = None,
    ) -> np.ndarray:
        if hedge_ratio is None or constant is None:
            hr, const = self.compute_hedge_ratio(prices_a, prices_b)
            hedge_ratio = float(hr)
            constant = float(const)

        spread = prices_a - hedge_ratio * prices_b - constant
        return spread

    def engle_granger_test(
        self, prices_a: np.ndarray, prices_b: np.ndarray, significance: float = 0.05
    ) -> CointegrationResult:
        if len(prices_a) < self.lookback or len(prices_b) < self.lookback:
            return CointegrationResult(
                is_cointegrated=False,
                p_value=1.0,
                hedge_ratio=1.0,
                constant=0.0,
                adf_statistic=0.0,
                adf_p_value=1.0,
            )

        n = min(len(prices_a), len(prices_b), self.lookback)
        pa = prices_a[-n:]
        pb = prices_b[-n:]

        hedge_ratio, constant = self.compute_hedge_ratio(pa, pb)
        spread = self.compute_spread(pa, pb, hedge_ratio, constant)

        adf_stat, adf_p = self._adf_test(spread)

        is_cointegrated = adf_p < significance

        return CointegrationResult(
            is_cointegrated=is_cointegrated,
            p_value=adf_p,
            hedge_ratio=hedge_ratio,
            constant=constant,
            adf_statistic=adf_stat,
            adf_p_value=adf_p,
        )

    def _adf_test(self, series: np.ndarray) -> Tuple[float, float]:
        if len(series) < 10:
            return 0.0, 1.0

        y = series[1:]
        x = series[:-1]

        if len(y) < 2 or len(x) < 2:
            return 0.0, 1.0

        x_with_const = np.column_stack([np.ones(len(x)), x])

        try:
            coeffs = np.linalg.lstsq(x_with_const, y, rcond=None)[0]
            residuals = y - x_with_const @ coeffs
        except np.linalg.LinAlgError:
            return 0.0, 1.0

        if len(residuals) < 2:
            return 0.0, 1.0

        resid_std = np.std(residuals, ddof=1)
        if resid_std < 1e-10:
            return 0.0, 1.0

        x_sum = np.sum(x)
        x_sq_sum = np.sum(x ** 2)
        if x_sq_sum - x_sum ** 2 / len(x) < 1e-10:
            return 0.0, 1.0

        theta = coeffs[1]

        try:
            s = np.sqrt(np.sum(residuals ** 2) / (len(residuals) - 2))
            se_theta = s / np.sqrt(x_sq_sum - x_sum ** 2 / len(x))
            t_stat = theta / se_theta
        except (ZeroDivisionError, FloatingPointError):
            return 0.0, 1.0

        n = len(series)
        approx_p = self._p_value_from_t(t_stat, n)

        return t_stat, approx_p

    def _p_value_from_t(self, t_stat: float, n: int) -> float:
        t_abs = abs(t_stat)
        if t_abs < 1.0:
            return 0.5
        if t_abs < 2.0:
            return 0.10
        if t_abs < 2.5:
            return 0.05
        if t_abs < 3.0:
            return 0.02
        if t_abs < 3.5:
            return 0.01
        return 0.001

    def compute_z_score(
        self,
        prices_a: np.ndarray,
        prices_b: np.ndarray,
        lookback: Optional[int] = None,
    ) -> SpreadStats:
        lb = lookback if lookback is not None else self.lookback
        n = min(len(prices_a), len(prices_b), lb)

        pa = prices_a[-n:]
        pb = prices_b[-n:]

        hedge_ratio, constant = self.compute_hedge_ratio(pa, pb)
        spread = self.compute_spread(pa, pb, hedge_ratio, constant)

        spread_mean = float(np.mean(spread))
        spread_std = float(np.std(spread, ddof=1))

        if spread_std < 1e-10:
            z_score = 0.0
        else:
            z_score = (spread[-1] - spread_mean) / spread_std

        return SpreadStats(
            mean=spread_mean,
            std=spread_std,
            z_score=z_score,
            spread=spread[-1],
        )

    def rolling_cointegration(
        self,
        prices_a: np.ndarray,
        prices_b: np.ndarray,
        window: int,
        step: int = 1,
    ) -> list:
        results = []
        for i in range(0, len(prices_a) - window, step):
            pa_window = prices_a[i : i + window]
            pb_window = prices_b[i : i + window]
            result = self.engle_granger_test(pa_window, pb_window)
            spread_stats = self.compute_z_score(pa_window, pb_window, window)
            results.append(
                {
                    "index": i,
                    "window_start": i,
                    "window_end": i + window,
                    "is_cointegrated": result.is_cointegrated,
                    "p_value": result.p_value,
                    "hedge_ratio": result.hedge_ratio,
                    "z_score": spread_stats.z_score,
                    "spread_mean": spread_stats.mean,
                    "spread_std": spread_stats.std,
                }
            )
        return results


class PairsSignalGenerator:
    def __init__(
        self,
        entry_threshold: float = 2.0,
        exit_threshold: float = 0.0,
        stop_loss_threshold: float = 3.0,
        lookback: int = 60,
    ):
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.stop_loss_threshold = stop_loss_threshold
        self.cointegration_engine = CointegrationEngine(lookback=lookback)
        self.lookback = lookback
        self._hedge_ratio: Optional[float] = None
        self._constant: Optional[float] = None
        self._in_position: bool = False
        self._position_side: Optional[str] = None

    def reset(self):
        self._hedge_ratio = None
        self._constant = None
        self._in_position = False
        self._position_side = None

    def update_cointegration(
        self, prices_a: np.ndarray, prices_b: np.ndarray
    ) -> bool:
        result = self.cointegration_engine.engle_granger_test(prices_a, prices_b)
        if result.is_cointegrated:
            self._hedge_ratio = result.hedge_ratio
            self._constant = result.constant
            return True
        return False

    def compute_spread(
        self, prices_a: np.ndarray, prices_b: np.ndarray
    ) -> Optional[float]:
        if self._hedge_ratio is None:
            return None
        return prices_a[-1] - self._hedge_ratio * prices_b[-1] - self._constant

    def compute_z_score(
        self, prices_a: np.ndarray, prices_b: np.ndarray
    ) -> Optional[float]:
        if self._hedge_ratio is None:
            return None

        spread_stats = self.cointegration_engine.compute_z_score(
            prices_a, prices_b, self.lookback
        )
        return spread_stats.z_score

    def generate_signal(
        self, prices_a: np.ndarray, prices_b: np.ndarray
    ) -> Tuple[Optional[str], Optional[str]]:
        z_score = self.compute_z_score(prices_a, prices_b)

        if z_score is None:
            return None, None

        if not self._in_position:
            if z_score > self.entry_threshold:
                self._in_position = True
                self._position_side = "short"
                return "entry_short", "z_score_overbought"
            elif z_score < -self.entry_threshold:
                self._in_position = True
                self._position_side = "long"
                return "entry_long", "z_score_oversold"
            else:
                return None, None
        else:
            if self._position_side == "short":
                if z_score <= self.exit_threshold:
                    self._in_position = False
                    self._position_side = None
                    return "exit", "z_score_reverted"
                elif z_score > self.stop_loss_threshold:
                    self._in_position = False
                    self._position_side = None
                    return "stop_loss", "z_score_stopped"
                else:
                    return "hold_short", "maintaining_position"
            else:
                if z_score >= self.exit_threshold:
                    self._in_position = False
                    self._position_side = None
                    return "exit", "z_score_reverted"
                elif z_score < -self.stop_loss_threshold:
                    self._in_position = False
                    self._position_side = None
                    return "stop_loss", "z_score_stopped"
                else:
                    return "hold_long", "maintaining_position"


def parameter_sweep(
    prices_a: np.ndarray,
    prices_b: np.ndarray,
    lookbacks: list,
    entry_thresholds: list,
    exit_thresholds: list,
    stop_thresholds: list,
) -> list:
    results = []

    for lb in lookbacks:
        for entry in entry_thresholds:
            for exit_t in exit_thresholds:
                for stop in stop_thresholds:
                    if stop <= entry:
                        continue

                    generator = PairsSignalGenerator(
                        entry_threshold=entry,
                        exit_threshold=exit_t,
                        stop_loss_threshold=stop,
                        lookback=lb,
                    )

                    signals = []
                    for i in range(lb, len(prices_a)):
                        pa = prices_a[: i + 1]
                        pb = prices_b[: i + 1]
                        if not generator.update_cointegration(pa, pb):
                            continue
                        signal, reason = generator.generate_signal(pa, pb)
                        if signal and signal.startswith("entry"):
                            signals.append(signal)

                    results.append(
                        {
                            "lookback": lb,
                            "entry_threshold": entry,
                            "exit_threshold": exit_t,
                            "stop_loss_threshold": stop,
                            "num_signals": len(signals),
                        }
                    )

    return results