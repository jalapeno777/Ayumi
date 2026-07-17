from __future__ import annotations

import argparse
import sys
from typing import Any

from hybrid.engine import HybridEngine, HybridEngineConfig
from hybrid.risk_manager import RiskManager
from hybrid.signal import HumanSignal, SignalSource, SignalType
from risk.correlation_sizer import CorrelationAwareSizer
from risk.correlation_matrix import CorrelationMatrix


def _parse_kv_args(args: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for arg in args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            result[key.strip()] = value.strip()
        else:
            result[arg.strip()] = arg.strip()
    return result


def _validate_signal_kwargs(kwargs: dict[str, str]) -> list[str]:
    errors: list[str] = []
    valid_keys = {
        "entry",
        "sl",
        "tp1",
        "tp",
        "volume",
        "lot_size",
        "confidence",
        "rationale",
        "source",
    }
    for key in kwargs:
        if key not in valid_keys:
            errors.append(f"Unknown parameter: {key}")

    if "entry" not in kwargs:
        errors.append("Missing required parameter: entry")
    else:
        try:
            float(kwargs["entry"])
        except ValueError:
            errors.append(f"Invalid entry price: {kwargs['entry']}")

    if "sl" not in kwargs:
        errors.append("Missing required parameter: sl")
    else:
        try:
            sl_val = float(kwargs["sl"])
            if sl_val <= 0:
                errors.append(f"Stop loss must be positive, got {sl_val}")
        except ValueError:
            errors.append(f"Invalid stop loss: {kwargs['sl']}")

    for tp_key in ("tp1", "tp"):
        if tp_key in kwargs:
            try:
                float(kwargs[tp_key])
            except ValueError:
                errors.append(f"Invalid take profit: {kwargs[tp_key]}")

    if "confidence" in kwargs:
        try:
            conf = float(kwargs["confidence"])
            if not (0.0 <= conf <= 1.0):
                errors.append(f"Confidence must be 0.0-1.0, got {conf}")
        except ValueError:
            errors.append(f"Invalid confidence: {kwargs['confidence']}")

    if "volume" in kwargs:
        try:
            vol = float(kwargs["volume"])
            if vol <= 0:
                errors.append(f"Volume must be positive, got {vol}")
        except ValueError:
            errors.append(f"Invalid volume: {kwargs['volume']}")

    if "lot_size" in kwargs:
        try:
            ls = float(kwargs["lot_size"])
            if ls <= 0:
                errors.append(f"Lot size must be positive, got {ls}")
        except ValueError:
            errors.append(f"Invalid lot size: {kwargs['lot_size']}")

    return errors


def _build_signal(direction: str, pair: str, kwargs: dict[str, str]) -> HumanSignal:
    signal_type = SignalType(direction.lower())
    entry_price = float(kwargs["entry"])
    stop_loss = float(kwargs["sl"]) if "sl" in kwargs else None
    tp_key = "tp1" if "tp1" in kwargs else "tp"
    take_profit = float(kwargs[tp_key]) if tp_key in kwargs else None
    confidence = float(kwargs["confidence"]) if "confidence" in kwargs else None

    source_str = kwargs.get("source", "manual").lower()
    source = (
        SignalSource(source_str)
        if source_str in SignalSource.__members__
        else SignalSource.MANUAL
    )

    return HumanSignal(
        signal_type=signal_type,
        pair=pair,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        confidence=confidence,
        source=source,
    )


def _format_signal_result(result: Any) -> str:
    lines: list[str] = []
    if result.success:
        lines.append(f"ACCEPTED  order={result.order_id} position={result.position_id}")
        if result.lot_size:
            lines.append(f"  lot_size={result.lot_size:.2f}")
        if result.risk_decision and result.risk_decision.risk_reward is not None:
            lines.append(f"  risk_reward={result.risk_decision.risk_reward:.2f}")
        lines.append(
            f"  pair={result.signal.pair} direction={result.signal.to_direction_str()}"
        )
        lines.append(
            f"  entry={result.signal.entry_price:.5f} sl={result.signal.stop_loss} tp={result.signal.take_profit}"
        )
    else:
        lines.append("REJECTED")
        lines.append(f"  reason: {result.error}")
    return "\n".join(lines)


def _format_status(engine: HybridEngine) -> str:
    rm = engine.risk_manager
    lines: list[str] = []
    lines.append("=== Account Status ===")
    lines.append(f"  Balance:       ${rm.current_balance:,.2f}")
    lines.append(f"  Daily trades:  {rm.daily_trade_count}")
    lines.append(f"  Daily loss:    {rm.daily_loss_pct:.2f}%")
    lines.append(f"  Total DD:      {rm.total_drawdown_pct:.2f}%")
    lines.append(f"  Open positions: {rm.open_position_count}")
    lines.append("")
    positions = engine.get_open_positions()
    if positions:
        lines.append("=== Open Positions ===")
        for pos in positions:
            lines.append(
                f"  {pos['position_id']}  {pos['pair']} {pos['direction']} "
                f"lots={pos['lot_size']:.2f} entry={pos['entry_price']:.5f}"
            )
    else:
        lines.append("No open positions.")
    return "\n".join(lines)


def _format_positions(engine: HybridEngine) -> str:
    positions = engine.get_open_positions()
    if not positions:
        return "No open positions."
    lines: list[str] = ["=== Open Positions ==="]
    for pos in positions:
        sl_str = f"{pos['stop_loss']:.5f}" if pos["stop_loss"] else "none"
        tp_str = f"{pos['take_profit']:.5f}" if pos["take_profit"] else "none"
        lines.append(f"  {pos['position_id']}  {pos['pair']} {pos['direction']}")
        lines.append(f"    lots={pos['lot_size']:.2f}  entry={pos['entry_price']:.5f}")
        lines.append(f"    sl={sl_str}  tp={tp_str}")
    return "\n".join(lines)


def _format_close_result(result: Any, position_id: str) -> str:
    if result.success:
        return f"Position {position_id} closed."
    return f"FAILED: {result.error}"


def create_engine(
    starting_balance: float = 100_000.0,
    session_filter_enabled: bool = True,
    correlation_matrix: CorrelationMatrix | None = None,
    use_kelly_sizing: bool = False,
) -> HybridEngine:
    """Create a HybridEngine with optional correlation-aware sizing.

    When *correlation_matrix* is provided, a :class:`CorrelationAwareSizer`
    is instantiated and passed to the :class:`RiskManager` so that
    cross-strategy correlation penalties apply to live position sizing.

    *use_kelly_sizing* enables Half-Kelly position sizing (default off).
    """
    correlation_sizer: CorrelationAwareSizer | None = None
    if correlation_matrix is not None:
        correlation_sizer = CorrelationAwareSizer(
            correlation_matrix=correlation_matrix,
        )

    config = HybridEngineConfig(
        session_filter_enabled=session_filter_enabled,
        use_kelly_sizing=use_kelly_sizing,
    )
    risk_manager = RiskManager(
        starting_balance=starting_balance,
        correlation_sizer=correlation_sizer,
    )
    return HybridEngine(
        risk_manager=risk_manager,
        starting_balance=starting_balance,
        config=config,
        correlation_sizer=correlation_sizer,
    )


def cmd_signal(args: list[str], engine: HybridEngine) -> str:
    if len(args) < 2:
        return 'Usage: signal <BUY|SELL> <PAIR> entry=<price> sl=<price> [tp1=<price>] [confidence=<0.0-1.0>] [rationale="..."]'

    direction = args[0]
    if direction.upper() not in ("BUY", "SELL"):
        return f"Invalid direction: {direction}. Must be BUY or SELL."

    pair = args[1]
    kwargs = _parse_kv_args(args[2:])

    errors = _validate_signal_kwargs(kwargs)
    if errors:
        return "Validation errors:\n  " + "\n  ".join(errors)

    try:
        signal = _build_signal(direction, pair, kwargs)
    except (ValueError, KeyError) as e:
        return f"Error building signal: {e}"

    result = engine.submit_signal(signal)
    return _format_signal_result(result)


def cmd_status(args: list[str], engine: HybridEngine) -> str:
    return _format_status(engine)


def cmd_positions(args: list[str], engine: HybridEngine) -> str:
    return _format_positions(engine)


def cmd_close(args: list[str], engine: HybridEngine) -> str:
    if not args:
        return "Usage: close <position_id>"
    position_id = args[0]
    result = engine.close_position(position_id)
    return _format_close_result(result, position_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hybrid",
        description="Ayumi Hybrid Trading CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    signal_parser = subparsers.add_parser("signal", help="Submit a trade signal")
    signal_parser.add_argument(
        "direction", choices=["BUY", "SELL"], help="Trade direction"
    )
    signal_parser.add_argument("pair", help="Currency pair (e.g., EURUSD)")
    signal_parser.add_argument(
        "kwargs", nargs="*", help="Signal parameters (entry=X sl=Y tp1=Z ...)"
    )

    subparsers.add_parser("status", help="Show account status")
    subparsers.add_parser("positions", help="List open positions")

    close_parser = subparsers.add_parser("close", help="Close a position")
    close_parser.add_argument("position_id", help="Position ID to close")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    engine = create_engine(session_filter_enabled=False)
    cmd_map = {
        "signal": cmd_signal,
        "status": cmd_status,
        "positions": cmd_positions,
        "close": cmd_close,
    }

    handler = cmd_map.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "signal":
        raw = [args.direction, args.pair] + (args.kwargs or [])
        output = handler(raw, engine)
    elif args.command == "close":
        output = handler([args.position_id], engine)
    else:
        output = handler([], engine)

    print(output)
