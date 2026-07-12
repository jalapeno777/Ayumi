"""SRF Parameter Stability module.

Analyzes optimization landscape to detect overfitting via parameter
instability: heatmap generation, plateau detection, neighbor robustness,
cross-window rank correlation, and coefficient of variation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StabilityResult:
    """Parameter stability analysis result."""
    cv: float                          # Coefficient of variation of performance
    is_stable: bool                    # True if CV < threshold
    plateau_score: float               # 0 = spike, 1 = broad plateau
    neighbor_correlation: float        # Spearman correlation of neighbor performance
    cross_window_rank_correlation: float  # Mean Spearman rank correlation of params
    heatmap: np.ndarray | None = None  # [n_perturbations, n_params] performance grid
    detail: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "cv": float(self.cv),
            "is_stable": bool(self.is_stable),
            "plateau_score": float(self.plateau_score),
            "neighbor_correlation": float(self.neighbor_correlation),
            "cross_window_rank_correlation": float(self.cross_window_rank_correlation),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Core analyses
# ═══════════════════════════════════════════════════════════════════════════

def coefficient_of_variation(window_performances: Sequence[float]) -> float:
    """CV of a performance metric across walk-forward windows.

    Parameters
    ----------
    window_performances : Sharpe (or PF, expectancy) per window

    Returns
    -------
    CV = std / |mean|.  Lower = more stable.
    """
    arr = np.asarray(window_performances, dtype=float)
    if len(arr) < 2:
        return 0.0
    mean = np.mean(arr)
    if abs(mean) < 1e-12:
        return float("inf") if np.std(arr) > 0 else 0.0
    return float(np.std(arr, ddof=1) / abs(mean))


def plateau_detection(
    param_values: np.ndarray,
    performance: np.ndarray,
    threshold: float = 0.95,
) -> float:
    """Detect whether best performance is a spike or on a broad plateau.

    Parameters
    ----------
    param_values : [N, D] array of parameter sets (N trials, D dimensions)
    performance : [N] array of performance metric (higher = better)
    threshold : fraction of best performance that counts as "on plateau"

    Returns
    -------
    Plateau score in [0, 1].  1 = broad plateau, 0 = sharp spike.
    """
    if len(performance) == 0:
        return 0.0
    best = float(np.max(performance))
    if abs(best) < 1e-12:
        return 0.0
    on_plateau = performance >= threshold * best
    return float(np.mean(on_plateau))


def neighbor_robustness(
    param_values: np.ndarray,
    performance: np.ndarray,
    k: int = 5,
) -> float:
    """Check if nearby parameter sets perform similarly.

    For each trial, finds its k nearest neighbors in parameter space
    and computes the Spearman rank correlation of their performances.

    Returns
    -------
    Mean Spearman correlation in [-1, 1].  High = neighbors perform similarly.
    """
    from scipy.stats import spearmanr
    N = len(performance)
    if N < k + 1:
        return 0.0

    # Normalize parameters to [0, 1]
    pmin = param_values.min(axis=0)
    pmax = param_values.max(axis=0)
    prange = np.where(pmax > pmin, pmax - pmin, 1.0)
    normalized = (param_values - pmin) / prange

    correlations = []
    for i in range(N):
        dists = np.sqrt(np.sum((normalized - normalized[i]) ** 2, axis=1))
        dists[i] = float("inf")  # exclude self
        neighbor_idx = np.argsort(dists)[:k]
        neighbor_perf = performance[neighbor_idx]
        center_perf = performance[i]

        # Correlation between distance and performance difference
        neighbor_dists = dists[neighbor_idx]
        perf_diffs = np.abs(neighbor_perf - center_perf)
        if len(neighbor_dists) > 2 and np.std(perf_diffs) > 0:
            r, _ = spearmanr(neighbor_dists, perf_diffs)
            if r is not None and math.isfinite(r):
                correlations.append(-r)  # negative because close distance should = small diff

    if not correlations:
        return 0.0
    return float(np.mean(correlations))


def cross_window_rank_correlation(
    window_results: list[dict[str, Any]],
) -> float:
    """Mean Spearman rank correlation of parameter performance across windows.

    Parameters
    ----------
    window_results : list of dicts, each containing 'params' (dict) and 'performance'

    Returns
    -------
    Mean pairwise Spearman correlation. High = consistent param ranking.
    """
    from scipy.stats import spearmanr

    if len(window_results) < 2:
        return 1.0

    # Extract parameter names
    param_names = sorted(window_results[0]["params"].keys())

    # Build performance vectors per window (indexed by parameter name)
    window_perf_vectors = []
    for w in window_results:
        vec = [w["params"].get(name, 0.0) for name in param_names]
        window_perf_vectors.append(np.array(vec))

    # Pairwise Spearman
    correlations = []
    for i in range(len(window_perf_vectors)):
        for j in range(i + 1, len(window_perf_vectors)):
            if (np.std(window_perf_vectors[i]) > 0 and
                    np.std(window_perf_vectors[j]) > 0):
                r, _ = spearmanr(window_perf_vectors[i], window_perf_vectors[j])
                if r is not None and math.isfinite(r):
                    correlations.append(r)

    if not correlations:
        return 0.0
    return float(np.mean(correlations))


# ═══════════════════════════════════════════════════════════════════════════
# Heatmap generation
# ═══════════════════════════════════════════════════════════════════════════

def generate_heatmap(
    evaluate_fn: callable,
    best_params: dict[str, float],
    perturbation_fractions: tuple[float, ...] = (-0.2, -0.1, 0.0, 0.1, 0.2),
) -> np.ndarray:
    """Generate performance heatmap by perturbing best params.

    Parameters
    ----------
    evaluate_fn : callable(dict[str, float]) -> float  (returns performance metric)
    best_params : best parameter set
    perturbation_fractions : perturbation levels relative to each param value

    Returns
    -------
    [len(perturbations), n_params] array of performance values.
    Column j corresponds to perturbing param j only.
    """
    param_names = sorted(best_params.keys())
    n_perturb = len(perturbation_fractions)
    n_params = len(param_names)
    heatmap = np.full((n_perturb, n_params), np.nan)

    for j, pname in enumerate(param_names):
        for i, frac in enumerate(perturbation_fractions):
            params = best_params.copy()
            params[pname] = best_params[pname] * (1.0 + frac)
            try:
                heatmap[i, j] = float(evaluate_fn(params))
            except Exception:
                logger.warning("Evaluation failed for %s=%s*%.2f", pname, best_params[pname], 1 + frac)

    return heatmap


# ═══════════════════════════════════════════════════════════════════════════
# Full stability assessment
# ═══════════════════════════════════════════════════════════════════════════

def assess_stability(
    window_performances: Sequence[float],
    param_values: np.ndarray,
    performance: np.ndarray,
    window_results: list[dict[str, Any]] | None = None,
    *,
    cv_threshold: float = 0.3,
    plateau_threshold: float = 0.95,
) -> StabilityResult:
    """Full parameter stability assessment.

    Parameters
    ----------
    window_performances : per-window Sharpe (or equivalent) values
    param_values : [N, D] array of all trial parameter sets
    performance : [N] array of trial performances
    window_results : optional, for cross-window rank correlation
    cv_threshold : max acceptable CV (default 0.3)
    plateau_threshold : fraction of best for plateau detection

    Returns
    -------
    StabilityResult with all metrics.
    """
    cv = coefficient_of_variation(window_performances)
    is_stable = cv < cv_threshold
    plateau = plateau_detection(param_values, performance, plateau_threshold)

    try:
        neighbor = neighbor_robustness(param_values, performance)
    except Exception:
        neighbor = 0.0
        logger.warning("Neighbor robustness computation failed")

    if window_results and len(window_results) >= 2:
        try:
            cwrc = cross_window_rank_correlation(window_results)
        except Exception:
            cwrc = 0.0
            logger.warning("Cross-window rank correlation computation failed")
    else:
        cwrc = 1.0  # default to stable if insufficient data

    detail = (
        f"CV={cv:.3f} ({'stable' if is_stable else 'unstable'}), "
        f"plateau={plateau:.3f}, neighbor_corr={neighbor:.3f}, "
        f"cross_window={cwrc:.3f}"
    )

    return StabilityResult(
        cv=cv,
        is_stable=is_stable,
        plateau_score=plateau,
        neighbor_correlation=neighbor,
        cross_window_rank_correlation=cwrc,
        detail=detail,
    )
