from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from ..models.trade import TradeSignal


class SignalFormat(Enum):
    DISCORD = "discord"
    WEBHOOK = "webhook"
    JSON = "json"


@dataclass
class SignalBroadcaster:
    format_type: SignalFormat = SignalFormat.DISCORD
    on_broadcast: Optional[Callable[[dict], None]] = None

    def format_signal(self, signal: TradeSignal | dict) -> dict:
        if isinstance(signal, TradeSignal):
            signal = {
                "provider_id": signal.provider_id,
                "symbol": signal.symbol,
                "direction": signal.direction.value,
                "entry_price": signal.entry_price,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "lot_size": signal.lot_size,
                "signal_time": signal.signal_time.isoformat(),
                "strategy_name": signal.strategy_name,
                "confluence_count": signal.confluence_count,
                "strength": signal.strength,
                "risk_reward": round(signal.risk_reward, 2),
            }

        if self.format_type == SignalFormat.DISCORD:
            signal["formatted"] = self._format_discord(signal)
        elif self.format_type == SignalFormat.JSON:
            signal["formatted"] = signal

        return signal

    def broadcast(self, signal: TradeSignal | dict) -> dict:
        formatted = self.format_signal(signal)
        if self.on_broadcast:
            self.on_broadcast(formatted)
        return formatted

    def _format_discord(self, signal: dict) -> str:
        direction_emoji = "🟢" if signal["direction"] == "long" else "🔴"
        rr = signal.get("risk_reward", 0)
        strength = signal.get("strength", "moderate")

        return (
            f"{direction_emoji} **{signal.get('strategy_name', 'Signal')}** | "
            f"`{signal['symbol']}` {signal['direction'].upper()}\n"
            f"Entry: `{signal['entry_price']}` | "
            f"SL: `{signal['stop_loss']}` | "
            f"TP: `{signal['take_profit']}`\n"
            f"RR: `{rr:.1f}` | Strength: `{strength}` | "
            f"Confluence: `{signal.get('confluence_count', 0)}`\n"
            f"Provider: `{signal.get('provider_id', 'unknown')}`"
        )


@dataclass
class WebhookHandler:
    providers: set[str] = field(default_factory=set)
    on_signal_received: Optional[Callable[[dict], None]] = None
    _logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    def handle_incoming(self, payload: dict) -> Optional[dict]:
        try:
            if not self._validate_payload(payload):
                self._logger.warning("Invalid webhook payload: %s", payload)
                return None

            provider_id = payload.get("provider_id", "")
            if self.providers and provider_id not in self.providers:
                self._logger.info("Signal from unknown provider: %s", provider_id)
                return None

            signal = {
                "provider_id": provider_id,
                "symbol": payload.get("symbol", ""),
                "direction": payload.get("direction", "").lower(),
                "entry_price": float(payload.get("entry_price", 0)),
                "stop_loss": float(payload.get("stop_loss", 0)),
                "take_profit": float(payload.get("take_profit", 0)),
                "lot_size": float(payload.get("lot_size", 0)),
                "signal_time": payload.get(
                    "signal_time", datetime.now(timezone.utc).isoformat()
                ),
                "strategy_name": payload.get("strategy_name", ""),
                "confluence_count": int(payload.get("confluence_count", 0)),
                "strength": payload.get("strength", "moderate"),
            }

            if self.on_signal_received:
                self.on_signal_received(signal)

            return signal
        except (ValueError, TypeError, KeyError) as e:
            self._logger.error("Error processing webhook: %s", e)
            return None

    def _validate_payload(self, payload: dict) -> bool:
        required = {"symbol", "direction", "entry_price", "stop_loss", "take_profit"}
        return required.issubset(payload.keys())
