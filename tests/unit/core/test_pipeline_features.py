"""Tests for PipelineFeatureExtractor."""

import pytest
from ml.pipeline_features import PipelineFeatureExtractor


@pytest.fixture
def extractor():
    return PipelineFeatureExtractor()


class TestSniperProfile:
    def test_extract_sniper(self, extractor):
        features = extractor.extract({"profile": "sniper"})
        assert features["profile_sniper"] == 1.0


class TestSwarmProfile:
    def test_extract_swarm(self, extractor):
        features = extractor.extract({"profile": "swarm"})
        assert features["profile_sniper"] == 0.0


class TestGateFeatures:
    def test_gate_pass_fail(self, extractor):
        features = extractor.extract({
            "gate_spread_pass": True,
            "gate_session_pass": False,
            "gate_volatility_pass": True,
        })
        assert features["gate_spread_pass"] == 1.0
        assert features["gate_session_pass"] == 0.0
        assert features["gate_volatility_pass"] == 1.0


class TestConfidenceBucket:
    def test_one_hot_encoding(self, extractor):
        low = extractor.extract({"confidence": 0.2})
        assert low["confidence_bucket_low"] == 1.0
        assert low["confidence_bucket_med"] == 0.0
        assert low["confidence_bucket_high"] == 0.0

        med = extractor.extract({"confidence": 0.5})
        assert med["confidence_bucket_low"] == 0.0
        assert med["confidence_bucket_med"] == 1.0
        assert med["confidence_bucket_high"] == 0.0

        high = extractor.extract({"confidence": 0.9})
        assert high["confidence_bucket_low"] == 0.0
        assert high["confidence_bucket_med"] == 0.0
        assert high["confidence_bucket_high"] == 1.0


class TestNormalizationBounds:
    def test_all_values_0_to_1(self, extractor):
        trade = {
            "profile": "sniper",
            "confidence": 0.8,
            "lots": 0.25,
            "risk_amount": 50.0,
            "account_balance": 10000.0,
            "sl_distance_pips": 25.0,
            "gate_spread_pass": True,
            "gate_session_pass": True,
            "gate_volatility_pass": True,
            "confluence_score": 0.7,
            "num_agreeing_strategies": 1,
        }
        features = extractor.extract(trade)
        for k, v in features.items():
            assert 0.0 <= v <= 1.0, f"{k} = {v} out of [0, 1]"


class TestFeatureNames:
    def test_names_match_extracted_keys(self, extractor):
        trade = {
            "profile": "sniper",
            "confidence": 0.5,
            "lots": 0.1,
            "risk_amount": 50.0,
            "account_balance": 10000.0,
        }
        features = extractor.extract(trade)
        assert list(features.keys()) == extractor.feature_names
