import logging
import os
from dataclasses import dataclass
from typing import Optional

from backtest.strategies import ISignalStrategy

from .models import (
    cTraderCredentials,
)
from .order_manager import PositionSizeConfig
from .paper_trader import PaperTrader
from .risk_guard import FTMOConfig
from .signal_adapter import cTraderSignalAdapter
from .trade_logger import TradeLogger

logger = logging.getLogger(__name__)

GBPUSD_FTMO_CONFIG = FTMOConfig(
    daily_loss_limit_pct=0.05,
    total_drawdown_limit_pct=0.10,
    max_trades_per_day=5,
    max_positions=1,
    min_risk_reward=1.0,
    max_position_size_pct=0.50,
    best_day_rule_max_pct=0.50,
)

GBPUSD_POSITION_CONFIG = PositionSizeConfig(
    risk_per_trade_pct=0.005,
    max_lot_size=0.5,
    min_lot_size=0.01,
    default_lot_size=0.05,
)

SYMBOL = "GBPUSD"


@dataclass
class SessionRangeGBPUSDConfig:
    starting_balance: float = 100000.0
    min_confidence: float = 0.50
    live_mode: bool = False
    log_dir: str = "logs/trades"
    use_fix: bool = False


def build_gbpusd_paper_trader(
    strategy: ISignalStrategy,
    config: Optional[SessionRangeGBPUSDConfig] = None,
) -> tuple[PaperTrader, cTraderSignalAdapter, TradeLogger]:
    cfg = config or SessionRangeGBPUSDConfig()

    trader = PaperTrader(
        ftmo_config=GBPUSD_FTMO_CONFIG,
        position_config=GBPUSD_POSITION_CONFIG,
        starting_balance=cfg.starting_balance,
    )

    adapter = cTraderSignalAdapter(
        paper_trader=trader,
        strategy=strategy,
        symbol=SYMBOL,
    )
    adapter.set_min_confidence(cfg.min_confidence)

    trade_logger = TradeLogger(
        log_dir=cfg.log_dir,
        strategy_name="session_range_mr_gbpusd",
    )

    trader.register_callback("on_trade_executed", _on_trade_executed(trade_logger))
    trader.register_callback("on_position_closed", _on_position_closed(trade_logger))

    return trader, adapter, trade_logger


def build_gbpusd_live_trader(
    strategy: ISignalStrategy,
    credentials: cTraderCredentials,
    config: Optional[SessionRangeGBPUSDConfig] = None,
) -> tuple[PaperTrader, cTraderSignalAdapter, TradeLogger]:
    from .api_client import cTraderAPIClient

    cfg = config or SessionRangeGBPUSDConfig()
    cfg.live_mode = True

    api_client = cTraderAPIClient(credentials)
    api_client.set_paper_mode(False)

    trader = PaperTrader(
        ftmo_config=GBPUSD_FTMO_CONFIG,
        position_config=GBPUSD_POSITION_CONFIG,
        starting_balance=cfg.starting_balance,
        api_client=api_client,
    )

    adapter = cTraderSignalAdapter(
        paper_trader=trader,
        strategy=strategy,
        symbol=SYMBOL,
    )
    adapter.set_min_confidence(cfg.min_confidence)

    trade_logger = TradeLogger(
        log_dir=cfg.log_dir,
        strategy_name="session_range_mr_gbpusd",
    )

    trader.register_callback("on_trade_executed", _on_trade_executed(trade_logger))
    trader.register_callback("on_position_closed", _on_position_closed(trade_logger))

    return trader, adapter, trade_logger


def _on_trade_executed(trade_logger: TradeLogger):
    def callback(result):
        if result.order and result.position:
            trade_logger.log_trade_opened(result.order, result.position)

    return callback


def _on_position_closed(trade_logger: TradeLogger):
    def callback(position):
        trade_logger.log_position_closed(position)

    return callback


def load_credentials_from_env() -> cTraderCredentials:
    from dotenv import load_dotenv

    load_dotenv("/home/TacoPants/projects/Ayumi/.env")
    return cTraderCredentials(
        host=os.environ.get("CTRADER_HOST", ""),
        port=int(os.environ.get("CTRADER_SSL_PORT", "5202")),
        use_ssl=False,
        sender_comp_id=os.environ.get("CTRADER_SENDER_COMP_ID", ""),
        target_comp_id=os.environ.get("CTRADER_TARGET_COMP_ID", "cServer"),
        sender_sub_id=os.environ.get("CTRADER_SENDER_SUB_ID", "TRADE"),
        username=os.environ.get("CTRADER_ACCOUNT", ""),
        password=os.environ.get("CTRADER_PASSWORD", ""),
    )
