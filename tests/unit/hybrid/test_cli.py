import unittest

from hybrid.cli import (
    _build_signal,
    _format_close_result,
    _format_positions,
    _format_signal_result,
    _format_status,
    _parse_kv_args,
    _validate_signal_kwargs,
    build_parser,
    cmd_close,
    cmd_positions,
    cmd_signal,
    cmd_status,
    create_engine,
)
from hybrid.engine import HybridEngine


def _make_engine() -> HybridEngine:
    return create_engine(session_filter_enabled=False)


class TestParseKvArgs(unittest.TestCase):
    def test_key_value_pairs(self):
        result = _parse_kv_args(["entry=1.2345", "sl=1.2330"])
        self.assertEqual(result, {"entry": "1.2345", "sl": "1.2330"})

    def test_bare_values(self):
        result = _parse_kv_args(["foo", "bar"])
        self.assertEqual(result, {"foo": "foo", "bar": "bar"})

    def test_mixed(self):
        result = _parse_kv_args(["entry=1.1", "bare"])
        self.assertEqual(result, {"entry": "1.1", "bare": "bare"})

    def test_empty(self):
        result = _parse_kv_args([])
        self.assertEqual(result, {})

    def test_value_with_equals(self):
        result = _parse_kv_args(["rationale=hello=world"])
        self.assertEqual(result, {"rationale": "hello=world"})


class TestValidateSignalKwargs(unittest.TestCase):
    def test_valid_minimal(self):
        errors = _validate_signal_kwargs({"entry": "1.2345", "sl": "1.2330"})
        self.assertEqual(errors, [])

    def test_valid_full(self):
        errors = _validate_signal_kwargs(
            {
                "entry": "1.2345",
                "sl": "1.2330",
                "tp1": "1.2360",
                "confidence": "0.75",
                "rationale": "test",
            }
        )
        self.assertEqual(errors, [])

    def test_missing_entry(self):
        errors = _validate_signal_kwargs({"sl": "1.2330"})
        self.assertTrue(any("entry" in e for e in errors))

    def test_missing_sl(self):
        errors = _validate_signal_kwargs({"entry": "1.2345"})
        self.assertTrue(any("sl" in e.lower() for e in errors))

    def test_invalid_entry(self):
        errors = _validate_signal_kwargs({"entry": "abc", "sl": "1.2330"})
        self.assertTrue(any("Invalid entry" in e for e in errors))

    def test_invalid_sl(self):
        errors = _validate_signal_kwargs({"entry": "1.2345", "sl": "xyz"})
        self.assertTrue(any("Invalid stop loss" in e for e in errors))

    def test_negative_sl(self):
        errors = _validate_signal_kwargs({"entry": "1.2345", "sl": "-1.0"})
        self.assertTrue(any("positive" in e for e in errors))

    def test_invalid_confidence(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "confidence": "abc"}
        )
        self.assertTrue(any("Invalid confidence" in e for e in errors))

    def test_confidence_out_of_range(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "confidence": "1.5"}
        )
        self.assertTrue(any("0.0-1.0" in e for e in errors))

    def test_negative_confidence(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "confidence": "-0.1"}
        )
        self.assertTrue(any("0.0-1.0" in e for e in errors))

    def test_unknown_parameter(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "bogus": "val"}
        )
        self.assertTrue(any("Unknown parameter" in e for e in errors))

    def test_invalid_tp1(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "tp1": "notanumber"}
        )
        self.assertTrue(any("Invalid take profit" in e for e in errors))

    def test_invalid_volume(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "volume": "bad"}
        )
        self.assertTrue(any("Invalid volume" in e for e in errors))

    def test_negative_volume(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "volume": "-0.1"}
        )
        self.assertTrue(any("positive" in e for e in errors))

    def test_tp_alias(self):
        errors = _validate_signal_kwargs(
            {"entry": "1.2345", "sl": "1.2330", "tp": "1.2360"}
        )
        self.assertEqual(errors, [])


class TestBuildSignal(unittest.TestCase):
    def test_buy_signal(self):
        signal = _build_signal("BUY", "EURUSD", {"entry": "1.1000", "sl": "1.0990"})
        self.assertEqual(signal.signal_type.value, "buy")
        self.assertEqual(signal.pair, "EURUSD")
        self.assertAlmostEqual(signal.entry_price, 1.1000)
        self.assertAlmostEqual(signal.stop_loss, 1.0990)

    def test_sell_signal(self):
        signal = _build_signal("SELL", "GBPUSD", {"entry": "1.2600", "sl": "1.2650"})
        self.assertEqual(signal.signal_type.value, "sell")
        self.assertEqual(signal.pair, "GBPUSD")

    def test_with_tp1(self):
        signal = _build_signal(
            "BUY", "EURUSD", {"entry": "1.1", "sl": "1.09", "tp1": "1.12"}
        )
        self.assertAlmostEqual(signal.take_profit, 1.12)

    def test_with_tp_alias(self):
        signal = _build_signal(
            "BUY", "EURUSD", {"entry": "1.1", "sl": "1.09", "tp": "1.12"}
        )
        self.assertAlmostEqual(signal.take_profit, 1.12)

    def test_with_confidence(self):
        signal = _build_signal(
            "BUY", "EURUSD", {"entry": "1.1", "sl": "1.09", "confidence": "0.8"}
        )
        self.assertAlmostEqual(signal.confidence, 0.8)

    def test_invalid_direction_raises(self):
        with self.assertRaises(ValueError):
            _build_signal("HOLD", "EURUSD", {"entry": "1.1", "sl": "1.09"})


class TestCmdSignal(unittest.TestCase):
    def test_valid_buy_signal_accepted(self):
        engine = _make_engine()
        output = cmd_signal(
            [
                "BUY",
                "EURUSD",
                "entry=1.1000",
                "sl=1.0980",
                "tp1=1.1060",
                "confidence=0.75",
            ],
            engine,
        )
        self.assertIn("ACCEPTED", output)
        self.assertIn("position=", output)

    def test_valid_sell_signal_accepted(self):
        engine = _make_engine()
        output = cmd_signal(
            ["SELL", "GBPUSD", "entry=1.2600", "sl=1.2630", "tp1=1.2540"],
            engine,
        )
        self.assertIn("ACCEPTED", output)

    def test_missing_args(self):
        engine = _make_engine()
        output = cmd_signal([], engine)
        self.assertIn("Usage:", output)

    def test_invalid_direction(self):
        engine = _make_engine()
        output = cmd_signal(["HOLD", "EURUSD"], engine)
        self.assertIn("Invalid direction", output)

    def test_missing_entry(self):
        engine = _make_engine()
        output = cmd_signal(["BUY", "EURUSD", "sl=1.09"], engine)
        self.assertIn("Validation errors", output)

    def test_missing_sl(self):
        engine = _make_engine()
        output = cmd_signal(["BUY", "EURUSD", "entry=1.1"], engine)
        self.assertIn("Validation errors", output)

    def test_unknown_param(self):
        engine = _make_engine()
        output = cmd_signal(
            ["BUY", "EURUSD", "entry=1.1", "sl=1.09", "bogus=123"],
            engine,
        )
        self.assertIn("Unknown parameter", output)

    def test_rejected_by_risk(self):
        engine = _make_engine()
        for _ in range(10):
            engine.submit_signal(
                _build_signal(
                    "BUY",
                    "EURUSD",
                    {"entry": "1.1", "sl": "1.09", "tp1": "1.12"},
                )
            )
        output = cmd_signal(
            ["BUY", "EURUSD", "entry=1.1", "sl=1.09", "tp1=1.12"],
            engine,
        )
        self.assertIn("REJECTED", output)


class TestCmdStatus(unittest.TestCase):
    def test_status_output(self):
        engine = _make_engine()
        output = cmd_status([], engine)
        self.assertIn("Account Status", output)
        self.assertIn("Balance:", output)
        self.assertIn("100,000", output)

    def test_status_with_position(self):
        engine = _make_engine()
        cmd_signal(["BUY", "EURUSD", "entry=1.1", "sl=1.09", "tp1=1.12"], engine)
        output = cmd_status([], engine)
        self.assertIn("Open Positions", output)
        self.assertIn("EURUSD", output)


class TestCmdPositions(unittest.TestCase):
    def test_no_positions(self):
        engine = _make_engine()
        output = cmd_positions([], engine)
        self.assertEqual(output, "No open positions.")

    def test_with_open_position(self):
        engine = _make_engine()
        cmd_signal(["BUY", "EURUSD", "entry=1.1", "sl=1.09", "tp1=1.12"], engine)
        output = cmd_positions([], engine)
        self.assertIn("Open Positions", output)
        self.assertIn("EURUSD", output)
        self.assertIn("long", output)


class TestCmdClose(unittest.TestCase):
    def test_close_valid_position(self):
        engine = _make_engine()
        result = cmd_signal(
            ["BUY", "EURUSD", "entry=1.1", "sl=1.09", "tp1=1.12"], engine
        )
        pos_id = result.split("position=")[1].strip().split()[0]
        output = cmd_close([pos_id], engine)
        self.assertIn("closed", output)

    def test_close_invalid_position(self):
        engine = _make_engine()
        output = cmd_close(["pos-999999"], engine)
        self.assertIn("FAILED", output)

    def test_close_no_args(self):
        engine = _make_engine()
        output = cmd_close([], engine)
        self.assertIn("Usage:", output)


class TestFormatFunctions(unittest.TestCase):
    def test_format_signal_result_accepted(self):
        engine = _make_engine()
        result = engine.submit_signal(
            _build_signal(
                "BUY",
                "EURUSD",
                {"entry": "1.1", "sl": "1.09", "tp1": "1.12"},
            )
        )
        output = _format_signal_result(result)
        self.assertIn("ACCEPTED", output)
        self.assertIn("lot_size=", output)

    def test_format_signal_result_rejected(self):
        from hybrid.engine import OrderResult

        result = OrderResult(success=False, error="test error")
        output = _format_signal_result(result)
        self.assertIn("REJECTED", output)
        self.assertIn("test error", output)

    def test_format_close_result_success(self):
        from hybrid.engine import OrderResult

        result = OrderResult(success=True, position_id="pos-001")
        output = _format_close_result(result, "pos-001")
        self.assertIn("closed", output)

    def test_format_close_result_failure(self):
        from hybrid.engine import OrderResult

        result = OrderResult(success=False, error="not found")
        output = _format_close_result(result, "pos-001")
        self.assertIn("FAILED", output)


class TestBuildParser(unittest.TestCase):
    def test_signal_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["signal", "BUY", "EURUSD", "entry=1.1", "sl=1.09"])
        self.assertEqual(args.command, "signal")
        self.assertEqual(args.direction, "BUY")
        self.assertEqual(args.pair, "EURUSD")
        self.assertEqual(len(args.kwargs), 2)

    def test_status_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["status"])
        self.assertEqual(args.command, "status")

    def test_positions_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["positions"])
        self.assertEqual(args.command, "positions")

    def test_close_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["close", "pos-001"])
        self.assertEqual(args.command, "close")
        self.assertEqual(args.position_id, "pos-001")

    def test_no_command_returns_none(self):
        parser = build_parser()
        args = parser.parse_args([])
        self.assertIsNone(args.command)


class TestCreateEngine(unittest.TestCase):
    def test_default_engine(self):
        engine = create_engine()
        self.assertIsNotNone(engine)

    def test_custom_balance(self):
        engine = create_engine(starting_balance=50_000.0)
        self.assertAlmostEqual(engine.risk_manager.current_balance, 50_000.0)

    def test_session_filter_disabled(self):
        engine = create_engine(session_filter_enabled=False)
        self.assertIsNotNone(engine)


class TestEndToEnd(unittest.TestCase):
    def test_full_workflow(self):
        engine = _make_engine()
        signal_out = cmd_signal(
            [
                "BUY",
                "EURUSD",
                "entry=1.1000",
                "sl=1.0980",
                "tp1=1.1060",
                "confidence=0.8",
            ],
            engine,
        )
        self.assertIn("ACCEPTED", signal_out)

        pos_out = cmd_positions([], engine)
        self.assertIn("EURUSD", pos_out)

        status_out = cmd_status([], engine)
        self.assertIn("Open positions: 1", status_out)

        pos_id = signal_out.split("position=")[1].strip().split()[0]
        close_out = cmd_close([pos_id], engine)
        self.assertIn("closed", close_out)

        pos_out_after = cmd_positions([], engine)
        self.assertEqual(pos_out_after, "No open positions.")


if __name__ == "__main__":
    unittest.main()
