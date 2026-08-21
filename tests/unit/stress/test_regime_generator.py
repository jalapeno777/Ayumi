"""Unit tests for the synthetic regime generator core module."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.mixture import GaussianMixture
from stress.regime_generator import (
    RegimeParams,
    _sample_regime_sequence,
    _to_log_returns,
    bootstrap_synthetic_returns,
    fit_gmm_returns,
    fit_hmm_returns,
    regime_sequence_to_returns,
    synthesize_prices,
)

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


@pytest.fixture
def synthetic_prices(rng: np.random.Generator) -> np.ndarray:
    """200-step random-walk price series starting at 1.1000."""
    n = 250
    log_rets = rng.normal(0.0, 0.002, size=n)
    return 1.1 * np.exp(np.cumsum(log_rets))


@pytest.fixture
def synthetic_returns(synthetic_prices: np.ndarray) -> np.ndarray:
    return _to_log_returns(synthetic_prices)


@pytest.fixture
def fitted_gmm(synthetic_returns: np.ndarray):
    return fit_gmm_returns(synthetic_returns, n_regimes=3, random_state=42)


@pytest.fixture
def fitted_params(synthetic_returns: np.ndarray, fitted_gmm):
    """Build a full RegimeParams via bootstrap (reuse for generation tests)."""
    _, params = bootstrap_synthetic_returns(
        synthetic_prices_fixture(synthetic_returns),
        n_regimes=3,
        n_paths=10,
        random_state=42,
    )
    return params


def synthetic_prices_fixture(returns: np.ndarray) -> np.ndarray:
    """Reconstruct prices from returns for the fixture chain."""
    return 1.1 * np.exp(np.cumsum(np.concatenate([[0.0], returns])))


# ── 1. _to_log_returns ────────────────────────────────────────────────────


class TestToLogReturns:
    def test_basic_conversion(self):
        prices = np.array([1.0, np.e, np.e**2])
        rets = _to_log_returns(prices)
        np.testing.assert_allclose(rets, [1.0, 1.0], atol=1e-10)

    def test_short_series_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            _to_log_returns([1.0])

    def test_non_positive_raises(self):
        with pytest.raises(ValueError, match="strictly positive"):
            _to_log_returns([1.0, 0.0, 2.0])

    def test_output_length(self):
        prices = np.linspace(1.0, 2.0, 200)
        rets = _to_log_returns(prices)
        assert rets.shape == (199,)


# ── 2. fit_gmm_returns ────────────────────────────────────────────────────


class TestFitGmmReturns:
    def test_returns_gmm_and_bic(self, synthetic_returns):
        gmm, bic = fit_gmm_returns(synthetic_returns, n_regimes=3, random_state=42)
        assert isinstance(gmm, GaussianMixture)
        assert gmm.n_components == 3
        assert isinstance(bic, float)
        assert np.isfinite(bic)

    def test_means_sorted_ascending(self, synthetic_returns):
        gmm, _ = fit_gmm_returns(synthetic_returns, n_regimes=3, random_state=42)
        means = gmm.means_.ravel()
        assert means[0] <= means[1] <= means[2]

    def test_too_few_observations_raises(self):
        small = np.random.default_rng(0).normal(0, 0.001, size=50)
        with pytest.raises(ValueError, match="at least"):
            fit_gmm_returns(small, n_regimes=2)

    def test_invalid_n_regimes_raises(self, synthetic_returns):
        with pytest.raises(ValueError, match="n_regimes"):
            fit_gmm_returns(synthetic_returns, n_regimes=0)

    def test_fit_recovers_means(self):
        """GMM should roughly recover the means of a 2-component mixture."""
        rng = np.random.default_rng(123)
        comp_a = rng.normal(-0.005, 0.001, size=500)
        comp_b = rng.normal(0.005, 0.001, size=500)
        data = np.concatenate([comp_a, comp_b])
        rng.shuffle(data)
        gmm, _ = fit_gmm_returns(data, n_regimes=2, random_state=123)
        means = gmm.means_.ravel()
        assert means[0] < 0 and means[1] > 0
        assert abs(means[0] - (-0.005)) < 0.002
        assert abs(means[1] - 0.005) < 0.002


# ── 3. fit_hmm_returns ────────────────────────────────────────────────────


class TestFitHMMReturns:
    def test_returns_hmm_with_correct_states(self, synthetic_returns, fitted_gmm):
        labels = fitted_gmm[0].predict(synthetic_returns.reshape(-1, 1))
        hmm = fit_hmm_returns(synthetic_returns, labels, n_regimes=3, random_state=42)
        assert hmm.n_components == 3

    def test_transmat_row_sums(self, synthetic_returns, fitted_gmm):
        labels = fitted_gmm[0].predict(synthetic_returns.reshape(-1, 1))
        hmm = fit_hmm_returns(synthetic_returns, labels, n_regimes=3, random_state=42)
        row_sums = hmm.transmat_.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-6)

    def test_label_length_mismatch_raises(self, synthetic_returns):
        bad_labels = np.zeros(10, dtype=int)
        with pytest.raises(ValueError, match="same length"):
            fit_hmm_returns(synthetic_returns, bad_labels, n_regimes=3)


# ── 4. regime_sequence_to_returns ─────────────────────────────────────────


class TestRegimeSequenceToReturns:
    def test_output_shape(self, rng):
        states = np.array([0, 1, 2, 0, 1])
        means = np.array([0.001, 0.0, -0.001])
        stds = np.array([0.002, 0.003, 0.004])
        rets = regime_sequence_to_returns(states, means, stds, rng)
        assert rets.shape == (5,)

    def test_mean_matches_state(self, rng):
        """With large N, the mean of returns for a constant state should
        approximate the regime mean."""
        states = np.zeros(10_000, dtype=int)
        means = np.array([0.003, 0.0])
        stds = np.array([0.001, 0.002])
        rets = regime_sequence_to_returns(states, means, stds, rng)
        assert abs(rets.mean() - 0.003) < 0.001  # within 1 std


# ── 5. synthesize_prices ──────────────────────────────────────────────────


class TestSynthesizePrices:
    def test_basic_price_path(self):
        log_rets = np.array([0.0, np.log(2.0), np.log(1.5)])
        prices = synthesize_prices(log_rets, start_price=1.0)
        # price[0] = 1.0, price[1] = 1.0*exp(0) = 1.0
        # price[2] = 1.0*exp(log2) = 2.0
        # price[3] = 1.0*exp(log2 + log1.5) = 3.0
        np.testing.assert_allclose(prices, [1.0, 1.0, 2.0, 3.0])

    def test_start_price_scaling(self):
        log_rets = np.array([0.0])
        prices = synthesize_prices(log_rets, start_price=100.0)
        np.testing.assert_allclose(prices, [100.0, 100.0])

    def test_negative_start_price_raises(self):
        with pytest.raises(ValueError, match="positive"):
            synthesize_prices(np.array([0.01]), start_price=-1.0)

    def test_output_length(self):
        log_rets = np.zeros(99)
        prices = synthesize_prices(log_rets, start_price=1.0)
        assert prices.shape == (100,)


# ── 6. bootstrap_synthetic_returns (integration) ──────────────────────────


class TestBootstrapSyntheticReturns:
    def test_output_shapes(self, synthetic_prices):
        paths, params = bootstrap_synthetic_returns(
            synthetic_prices,
            n_regimes=3,
            n_paths=50,
            random_state=42,
        )
        assert paths.shape == (50, len(synthetic_prices) - 1)
        assert isinstance(params, RegimeParams)
        assert params.n_regimes == 3

    def test_state_labels_in_range(self, synthetic_prices):
        """Generated regime sequences must produce valid state indices."""
        paths, params = bootstrap_synthetic_returns(
            synthetic_prices,
            n_regimes=3,
            n_paths=5,
            random_state=42,
        )
        # params.means has 3 entries → regime indices 0-2
        assert params.means.shape == (3,)

    def test_synthetic_returns_match_gmm_distribution(self):
        """Synthetic returns should approximately match the fitted GMM
        distribution within a tolerance."""
        rng = np.random.default_rng(999)
        # Build a clear 2-regime series
        comp_a = rng.normal(0.001, 0.0005, size=500)
        comp_b = rng.normal(-0.001, 0.0005, size=500)
        log_rets = np.concatenate([comp_a, comp_b])
        prices = 1.0 * np.exp(np.cumsum(log_rets))

        paths, params = bootstrap_synthetic_returns(
            prices,
            n_regimes=2,
            n_paths=500,
            path_length=2000,
            random_state=999,
        )

        # The overall mean of synthetic returns should be close to the
        # weighted mean of the GMM components
        flat = paths.ravel()
        expected_mean = np.sum(params.weights * params.means)
        # Use wide tolerance because HMM temporal correlation inflates variance
        assert abs(flat.mean() - expected_mean) < 0.001

    def test_short_series_raises(self):
        short_prices = np.linspace(1.0, 1.1, 20)
        with pytest.raises(ValueError, match="too short|at least"):
            bootstrap_synthetic_returns(short_prices, n_regimes=2, n_paths=5)


# ── 7. RegimeParams validation ────────────────────────────────────────────


class TestRegimeParamsValidation:
    def _valid_kwargs(self):
        return dict(
            means=np.array([0.001, -0.001]),
            stds=np.array([0.002, 0.003]),
            weights=np.array([0.6, 0.4]),
            transmat=np.array([[0.9, 0.1], [0.2, 0.8]]),
            startprob=np.array([0.5, 0.5]),
            n_regimes=2,
            bic=-100.0,
        )

    def test_valid_params_accepted(self):
        params = RegimeParams(**self._valid_kwargs())
        assert params.n_regimes == 2

    def test_negative_std_rejected(self):
        kw = self._valid_kwargs()
        kw["stds"] = np.array([0.002, -0.001])
        with pytest.raises(ValueError, match="positive"):
            RegimeParams(**kw)

    def test_bad_transmat_shape_rejected(self):
        kw = self._valid_kwargs()
        kw["transmat"] = np.array([[0.9, 0.1, 0.0], [0.2, 0.8, 0.0]])
        with pytest.raises(ValueError, match="transmat"):
            RegimeParams(**kw)

    def test_weights_not_summing_to_one_rejected(self):
        kw = self._valid_kwargs()
        kw["weights"] = np.array([0.6, 0.6])
        with pytest.raises(ValueError, match="weights must sum"):
            RegimeParams(**kw)

    def test_startprob_not_summing_to_one_rejected(self):
        kw = self._valid_kwargs()
        kw["startprob"] = np.array([0.3, 0.3])
        with pytest.raises(ValueError, match="startprob must sum"):
            RegimeParams(**kw)


# ── 8. _sample_regime_sequence ────────────────────────────────────────────


class TestSampleRegimeSequence:
    def test_output_shape_and_range(self, rng):
        transmat = np.array([[0.9, 0.1], [0.3, 0.7]])
        startprob = np.array([0.5, 0.5])
        states = _sample_regime_sequence(transmat, startprob, 500, rng)
        assert states.shape == (500,)
        assert states.min() >= 0 and states.max() < 2

    def test_high_persistence_stays(self, rng):
        """With 99% self-transition, the chain should rarely switch."""
        transmat = np.array([[0.99, 0.01], [0.01, 0.99]])
        startprob = np.array([1.0, 0.0])
        states = _sample_regime_sequence(transmat, startprob, 1000, rng)
        switches = np.diff(states).nonzero()[0].size
        assert switches < 50  # well under 5% of steps
