"""Tests for ML confidence pipeline — confluence features, learner, integration."""

from __future__ import annotations

import unittest

from ml.confluence_features import ConfluenceFeatureExtractor
from ml.confidence_learner import ConfidenceLearner


class TestConfluenceFeatureExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ConfluenceFeatureExtractor()

    def test_feature_names_count(self):
        self.assertEqual(len(self.extractor.FEATURE_NAMES), 16)

    def test_extract_all_boosts_present(self):
        record = {
            "rationale": (
                "TTSStrategy: M long @ 1.08500, conf=0.75, "
                "boosts=[('rsi_divergence', 0.05), ('htf_trend_aligned', 0.08), "
                "('kill_zone_active', 0.05), ('vwap_rejection', 0.05), "
                "('consolidation', 0.04), ('quality_gate', 0.09)]"
            ),
            "confidence_score": 0.75,
            "confluence_count": 6,
        }
        features = self.extractor.extract(record)
        self.assertEqual(len(features), 16)

        # Binary features that should be 1
        self.assertEqual(features[0], 1.0)  # rsi_divergence
        self.assertEqual(features[1], 1.0)  # htf_trend_aligned
        self.assertEqual(features[6], 1.0)  # vwap_rejection
        self.assertEqual(features[3], 1.0)  # consolidation
        self.assertEqual(features[7], 1.0)  # kill_zone_active

        # Features that should be 0
        self.assertEqual(features[2], 0.0)  # svc_at_peak
        self.assertEqual(features[4], 0.0)  # asia_gap_favorable

        # Numeric features
        self.assertEqual(features[13], 0.75)  # confidence_score
        self.assertEqual(features[15], 6.0)  # confluence_count

    def test_extract_no_boosts(self):
        record = {
            "rationale": "TTSStrategy: W short @ 1.27000, conf=0.55, boosts=[]",
            "confidence_score": 0.55,
            "confluence_count": 0,
        }
        features = self.extractor.extract(record)
        # All binary features should be 0
        for i in range(13):
            self.assertEqual(features[i], 0.0)
        self.assertEqual(features[13], 0.55)  # confidence_score

    def test_extract_penalty_boosts(self):
        record = {
            "rationale": (
                "TTSStrategy: M long @ 1.08500, conf=0.45, "
                "boosts=[('htf_opposing', -0.15), ('htf_conflicting', -0.10)]"
            ),
            "confidence_score": 0.45,
            "confluence_count": 0,
        }
        features = self.extractor.extract(record)
        self.assertEqual(features[10], 1.0)  # htf_opposing
        self.assertEqual(features[11], 1.0)  # htf_conflicting
        self.assertEqual(features[12], 0.0)  # htf_consolidating

    def test_extract_empty_rationale(self):
        record = {"rationale": "", "confidence_score": 0.5, "confluence_count": 0}
        features = self.extractor.extract(record)
        self.assertEqual(len(features), 16)
        for f in features[:13]:
            self.assertEqual(f, 0.0)

    def test_extract_batch(self):
        records = [
            {
                "rationale": "boosts=[('rsi_divergence', 0.05)]",
                "confidence_score": 0.6,
                "confluence_count": 1,
            },
            {
                "rationale": "boosts=[('kill_zone_active', 0.05)]",
                "confidence_score": 0.7,
                "confluence_count": 1,
            },
        ]
        batch = self.extractor.extract_batch(records)
        self.assertEqual(len(batch), 2)
        self.assertEqual(len(batch[0]), 16)

    def test_parse_boosts_unknown_name(self):
        """Unknown boost names should still be captured with their original name."""
        record = {
            "rationale": "boosts=[('some_new_boost', 0.03)]",
            "confidence_score": 0.5,
            "confluence_count": 0,
        }
        features = self.extractor.extract(record)
        # 'some_new_boost' maps to itself (not in BOOST_TO_FEATURE), so no known feature = 1
        self.assertTrue(all(f == 0.0 for f in features[:13]))


class TestConfidenceLearner(unittest.TestCase):
    def setUp(self):
        self.feature_names = ConfluenceFeatureExtractor.FEATURE_NAMES

    def _make_records(self, n: int, win_rate: float = 0.5) -> list[dict]:
        """Generate synthetic trade records."""
        import random

        random.seed(42)
        records = []
        for i in range(n):
            outcome = 1 if random.random() < win_rate else 0
            # Feature 0 (rsi_divergence) correlated with wins when win_rate > 0.5
            rsi = 1.0 if (outcome == 1 and random.random() < 0.7) else 0.0
            features = [0.0] * 16
            features[0] = rsi
            features[13] = 0.5 + random.random() * 0.3  # confidence
            features[14] = 0.4 + random.random() * 0.2  # base_confidence
            features[15] = float(random.randint(0, 5))
            records.append({"features": features, "outcome": outcome})
        return records

    def test_train_minimum_trades(self):
        learner = ConfidenceLearner("TEST", "M15")
        records = self._make_records(19)
        with self.assertRaises(ValueError) as ctx:
            learner.train(records, self.feature_names)
        self.assertIn("20", str(ctx.exception))

    def test_train_and_predict(self):
        learner = ConfidenceLearner("TEST", "M15")
        records = self._make_records(50, win_rate=0.6)
        weights = learner.train(records, self.feature_names)
        self.assertTrue(learner.is_trained)
        self.assertEqual(len(weights), 16)
        self.assertIn("rsi_divergence", weights)

        # Predict on a record with rsi_divergence
        features = [
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.7,
            0.5,
            2.0,
        ]
        proba = learner.predict_proba(features)
        self.assertGreaterEqual(proba, 0.0)
        self.assertLessEqual(proba, 1.0)

    def test_predict_untrained(self):
        learner = ConfidenceLearner("TEST", "M15")
        proba = learner.predict_proba([0.0] * 16)
        self.assertEqual(proba, 0.5)

    def test_get_top_features(self):
        learner = ConfidenceLearner("TEST", "M15")
        records = self._make_records(30)
        learner.train(records, self.feature_names)
        top5 = learner.get_top_features(5)
        self.assertEqual(len(top5), 5)
        # Should be sorted descending
        for i in range(len(top5) - 1):
            self.assertGreaterEqual(top5[i][1], top5[i + 1][1])

    def test_all_zeros_features(self):
        """Model should handle all-zero feature vectors without crashing."""
        learner = ConfidenceLearner("TEST", "M15")
        records = self._make_records(25)
        learner.train(records, self.feature_names)
        proba = learner.predict_proba([0.0] * 16)
        self.assertIsInstance(proba, float)


class TestIntegration(unittest.TestCase):
    """Integration test: extract features → train → predict on same features."""

    def test_end_to_end(self):
        extractor = ConfluenceFeatureExtractor()
        learner = ConfidenceLearner("EURUSD", "M15")

        # Simulate trade records from backtest
        trade_records = []
        for i in range(30):
            boosts = "rsi_divergence" if i % 3 == 0 else ""
            if i % 4 == 0:
                boosts += ", htf_trend_aligned" if boosts else "htf_trend_aligned"
            rationale = (
                f"TTSStrategy: M long, conf=0.6, boosts=[({boosts}, 0.05)]"
                if boosts
                else "TTSStrategy: M long, conf=0.5, boosts=[]"
            )
            record = {
                "rationale": rationale,
                "confidence_score": 0.5 + (i % 10) * 0.03,
                "confluence_count": 1 if boosts else 0,
                "outcome": 1 if i % 2 == 0 else 0,
            }
            record["features"] = extractor.extract(record)
            trade_records.append(record)

        learner.train(trade_records, extractor.FEATURE_NAMES)
        self.assertTrue(learner.is_trained)

        # Predict on a new trade
        new_trade = {
            "rationale": "TTSStrategy: M long, conf=0.7, boosts=[('rsi_divergence', 0.05), ('htf_trend_aligned', 0.08)]",
            "confidence_score": 0.7,
            "confluence_count": 2,
        }
        features = extractor.extract(new_trade)
        proba = learner.predict_proba(features)
        self.assertGreaterEqual(proba, 0.0)
        self.assertLessEqual(proba, 1.0)


if __name__ == "__main__":
    unittest.main()
