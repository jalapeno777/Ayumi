"""Tests for symbol-type gating and instrument classification.

Covers:
- SymbolType enum has all 7 variants
- classify_symbol() heuristic for forex, crypto, metal, index
- SymbolTypeGate.check() routes crypto_perp to crypto detectors
- SymbolTypeGate.check() routes forex_major to forex detectors
- SymbolTypeGate.route() returns structured routing data
- get_detector_stack() returns correct detectors per type
- Instrument.is_forex / is_crypto properties
- Instrument.detector_stack property
"""

from __future__ import annotations  # noqa: I001

import pytest

from confidence.symbol_type_gating import (
    SymbolTypeGate,
    get_detector_stack,
)
from models.instrument import (
    DEFAULT_INSTRUMENTS,
    DETECTOR_STACK,
    Instrument,
    SymbolType,
    classify_symbol,
)


# ---------------------------------------------------------------------------
# SymbolType enum
# ---------------------------------------------------------------------------


class TestSymbolTypeEnum:
    """Verify the enum has all required variants."""

    def test_enum_has_seven_variants(self):
        """AC: symbol_type enum: crypto_perp | crypto_spot | forex_major | forex_cross | forex_exotic | metal | index"""
        expected = {
            "crypto_perp",
            "crypto_spot",
            "forex_major",
            "forex_cross",
            "forex_exotic",
            "metal",
            "index",
        }
        actual = {member.name for member in SymbolType}
        assert actual == expected, f"Missing members: {expected - actual}"

    def test_enum_values_are_strings(self):
        """Enum values should be lowercase string identifiers."""
        for member in SymbolType:
            assert isinstance(member.value, str)
            assert member.value == member.name


# ---------------------------------------------------------------------------
# classify_symbol() heuristic
# ---------------------------------------------------------------------------


class TestClassifySymbol:
    """Verify the heuristic classifier routes symbols correctly."""

    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("EURUSD", SymbolType.forex_major),
            ("USDJPY", SymbolType.forex_major),
            ("GBPUSD", SymbolType.forex_major),
            ("AUDCAD", SymbolType.forex_major),
            ("EURJPY", SymbolType.forex_major),
        ],
    )
    def test_forex_major_classification(self, symbol, expected):
        result = classify_symbol(symbol)
        assert result == expected, f"{symbol} should be {expected.value}, got {result.value}"

    @pytest.mark.parametrize(
        "symbol,expected",
        [
            ("BTCUSDT", SymbolType.crypto_perp),
            ("ETHUSDT", SymbolType.crypto_perp),
            ("SOLUSDT", SymbolType.crypto_perp),
            ("BTCUSDT.PERP", SymbolType.crypto_perp),
        ],
    )
    def test_crypto_classification(self, symbol, expected):
        result = classify_symbol(symbol)
        assert result == expected, f"{symbol} should be {expected.value}, got {result.value}"

    def test_metal_classification(self):
        assert classify_symbol("XAUUSD") == SymbolType.metal
        assert classify_symbol("XAGUSD") == SymbolType.metal

    def test_index_classification(self):
        assert classify_symbol("US500") == SymbolType.index
        assert classify_symbol("NAS100") == SymbolType.index

    def test_exotic_fallback(self):
        """Unknown 6-char symbol with non-major currency → forex_exotic."""
        result = classify_symbol("USDTRY")
        assert result == SymbolType.forex_exotic


# ---------------------------------------------------------------------------
# SymbolTypeGate — crypto routing
# ---------------------------------------------------------------------------


class TestSymbolTypeGateCrypto:
    """AC: test_symbol_type_gating.py: crypto_perp routes to crypto detectors"""

    def test_crypto_perp_routes_to_crypto_detectors(self):
        """Crypto perp symbol must route to open_interest, funding_rate, liquidations."""
        gate = SymbolTypeGate()
        ctx = {"symbol": "BTCUSDT", "symbol_type": SymbolType.crypto_perp}
        result = gate.check(ctx)

        assert result.passed is True
        assert "crypto_perp" in result.reason
        assert "stack=crypto" in result.reason

        routing = gate.route(ctx)
        assert routing.is_crypto is True
        assert routing.is_forex is False
        assert "open_interest" in routing.detectors
        assert "funding_rate" in routing.detectors
        assert "liquidations" in routing.detectors

    def test_crypto_perp_detector_stack_unchanged(self):
        """AC: Crypto detector stack unchanged for crypto_perp symbols.

        The crypto detector stack must remain exactly:
        open_interest, funding_rate, liquidations
        """
        stack = get_detector_stack(SymbolType.crypto_perp)
        assert stack == ["open_interest", "funding_rate", "liquidations"]

    def test_crypto_spot_routes_to_oi_only(self):
        """Crypto spot symbols get only open_interest (no funding/liquidations)."""
        gate = SymbolTypeGate()
        routing = gate.route({"symbol": "BTCUSD", "symbol_type": SymbolType.crypto_spot})
        assert routing.is_crypto is True
        assert routing.detectors == ["open_interest"]


# ---------------------------------------------------------------------------
# SymbolTypeGate — forex routing
# ---------------------------------------------------------------------------


class TestSymbolTypeGateForex:
    """AC: test_symbol_type_gating.py: forex_major routes to forex detectors"""

    def test_forex_major_routes_to_forex_detectors(self):
        """Forex major symbol must route to cot_positioning, rate_differential, order_flow_proxy."""
        gate = SymbolTypeGate()
        ctx = {"symbol": "EURUSD", "symbol_type": SymbolType.forex_major}
        result = gate.check(ctx)

        assert result.passed is True
        assert "forex_major" in result.reason
        assert "stack=forex" in result.reason

        routing = gate.route(ctx)
        assert routing.is_forex is True
        assert routing.is_crypto is False
        assert "cot_positioning" in routing.detectors
        assert "rate_differential" in routing.detectors
        assert "order_flow_proxy" in routing.detectors

    def test_forex_major_does_not_route_to_crypto_detectors(self):
        """Forex symbols must NOT route to crypto-native detectors."""
        gate = SymbolTypeGate()
        routing = gate.route({"symbol": "USDJPY", "symbol_type": SymbolType.forex_major})

        assert "open_interest" not in routing.detectors
        assert "funding_rate" not in routing.detectors
        assert "liquidations" not in routing.detectors

    def test_forex_cross_routes_correctly(self):
        """Forex cross pairs get same detector stack as majors."""
        gate = SymbolTypeGate()
        routing = gate.route({"symbol": "EURJPY", "symbol_type": SymbolType.forex_cross})
        assert routing.is_forex is True
        assert "cot_positioning" in routing.detectors

    def test_forex_exotic_has_reduced_stack(self):
        """Exotic forex pairs get positioning + rate differential (no order flow proxy)."""
        stack = get_detector_stack(SymbolType.forex_exotic)
        assert "cot_positioning" in stack
        assert "rate_differential" in stack
        assert "order_flow_proxy" not in stack


# ---------------------------------------------------------------------------
# SymbolTypeGate — heuristic fallback
# ---------------------------------------------------------------------------


class TestSymbolTypeGateHeuristic:
    """Gate should fall back to heuristic classification for unregistered symbols."""

    def test_unregistered_symbol_uses_heuristic(self):
        """Symbol not in registry should be classified heuristically."""
        gate = SymbolTypeGate()
        # AUDCAD is a valid forex major but not in DEFAULT_INSTRUMENTS
        routing = gate.route({"symbol": "AUDCAD"})
        assert routing.symbol_type == SymbolType.forex_major
        assert routing.is_forex is True

    def test_registered_symbol_uses_registry_type(self):
        """Registered symbol should use the registry's symbol_type."""
        custom_registry = {
            "EURUSD": Instrument("EURUSD", SymbolType.crypto_perp),
        }
        gate = SymbolTypeGate(instrument_registry=custom_registry)
        routing = gate.route({"symbol": "EURUSD"})
        assert routing.symbol_type == SymbolType.crypto_perp
        assert routing.is_crypto is True

    def test_explicit_override_takes_precedence(self):
        """Explicit symbol_type in context should override registry."""
        gate = SymbolTypeGate()
        ctx = {
            "symbol": "EURUSD",
            "symbol_type": SymbolType.index,  # nonsensical but tests override
        }
        routing = gate.route(ctx)
        assert routing.symbol_type == SymbolType.index


# ---------------------------------------------------------------------------
# Instrument dataclass
# ---------------------------------------------------------------------------


class TestInstrument:
    """Test Instrument properties and detector_stack."""

    def test_is_forex_property(self):
        eur = DEFAULT_INSTRUMENTS["EURUSD"]
        assert eur.is_forex is True
        assert eur.is_crypto is False

    def test_is_crypto_property(self):
        btc = Instrument("BTCUSDT", SymbolType.crypto_perp)
        assert btc.is_crypto is True
        assert btc.is_forex is False

    def test_metal_is_neither_forex_nor_crypto(self):
        xau = DEFAULT_INSTRUMENTS["XAUUSD"]
        assert xau.is_forex is False
        assert xau.is_crypto is False

    def test_detector_stack_property(self):
        btc = Instrument("BTCUSDT", SymbolType.crypto_perp)
        assert btc.detector_stack == ["open_interest", "funding_rate", "liquidations"]

        eur = DEFAULT_INSTRUMENTS["EURUSD"]
        assert "cot_positioning" in eur.detector_stack


# ---------------------------------------------------------------------------
# Gate always passes
# ---------------------------------------------------------------------------


class TestGateBehavior:
    """SymbolTypeGate is a routing gate — it should always pass."""

    def test_gate_always_passes(self):
        """The gate should never reject a signal — it only routes."""
        gate = SymbolTypeGate()
        for symbol_type in SymbolType:
            ctx = {"symbol": "TEST", "symbol_type": symbol_type}
            result = gate.check(ctx)
            assert result.passed is True, f"Gate should pass for {symbol_type}"
            assert result.boost == 0.0

    def test_empty_symbol_does_not_crash(self):
        """Edge case: empty symbol string should not raise."""
        gate = SymbolTypeGate()
        result = gate.check({"symbol": ""})
        assert result.passed is True


# ---------------------------------------------------------------------------
# DETECTOR_STACK completeness
# ---------------------------------------------------------------------------


class TestDetectorStack:
    """Verify every SymbolType has a detector stack entry."""

    def test_all_symbol_types_have_stack(self):
        """Every enum member should have an entry in DETECTOR_STACK."""
        for member in SymbolType:
            assert member in DETECTOR_STACK, f"Missing detector stack for {member.name}"

    def test_crypto_perp_stack_has_three_detectors(self):
        assert len(DETECTOR_STACK[SymbolType.crypto_perp]) == 3

    def test_forex_major_stack_has_three_detectors(self):
        assert len(DETECTOR_STACK[SymbolType.forex_major]) == 3
