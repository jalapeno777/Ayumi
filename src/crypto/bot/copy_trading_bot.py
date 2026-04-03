from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from ..models.trade import TradeSignal
from ..services.broadcaster import SignalBroadcaster, WebhookHandler
from ..services.repository import TradeRepository


logger = logging.getLogger(__name__)


@dataclass
class CopyTradingBot:
    repo: TradeRepository = field(default_factory=lambda: TradeRepository())
    broadcaster: SignalBroadcaster = field(default_factory=SignalBroadcaster)
    webhook_handler: WebhookHandler = field(default_factory=WebhookHandler)
    _broadcast_log: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.webhook_handler.on_signal_received = self._on_signal

    def register_provider(
        self,
        provider_id: str,
        name: str,
        strategy: str = "",
        followers_count: int = 0,
    ) -> None:
        self.repo.upsert_provider(provider_id, name, strategy, followers_count)
        self.webhook_handler.providers.add(provider_id)
        logger.info("Registered provider: %s (%s)", name, provider_id)

    def receive_signal(self, payload: dict) -> Optional[dict]:
        signal = self.webhook_handler.handle_incoming(payload)
        if not signal:
            return None
        if signal["provider_id"] not in self.webhook_handler.providers:
            logger.warning("Rejected signal from unregistered provider: %s", signal["provider_id"])
            return None
        signal_id = self.repo.save_signal(signal)
        signal["signal_db_id"] = signal_id
        logger.info(
                "Signal saved: %s %s from %s (id=%s)",
                signal["direction"].upper(),
                signal["symbol"],
                signal["provider_id"],
                signal_id,
            )
        return signal

    def get_leaderboard(self, limit: int = 10) -> list[dict]:
        return self.repo.get_leaderboard(limit)

    def get_provider_stats(self, provider_id: str) -> dict:
        return self.repo.get_provider_stats(provider_id)

    def get_recent_signals(self, limit: int = 20) -> list[dict]:
        return self.repo.get_recent_signals(limit)

    def broadcast_signal(self, signal: TradeSignal | dict) -> dict:
        formatted = self.broadcaster.broadcast(signal)
        self._broadcast_log.append({
            "signal": formatted,
            "broadcasted_at": formatted.get("signal_time", ""),
        })
        sym = signal.symbol if isinstance(signal, TradeSignal) else signal.get("symbol", "?")
        d = signal.direction.value if isinstance(signal, TradeSignal) else signal.get("direction", "?")
        logger.info("Signal broadcast: %s %s", sym, d)
        return formatted

    def close_trade(self, trade_id: int, close_price: float, profit_loss: float) -> None:
        self.repo.close_trade(trade_id, close_price, profit_loss)
        logger.info("Trade %d closed at %.5f (P&L: %.2f)", trade_id, close_price, profit_loss)

    def _on_signal(self, signal: dict) -> None:
        logger.info("Webhook signal received: %s %s from %s", signal["symbol"], signal["direction"], signal["provider_id"])
