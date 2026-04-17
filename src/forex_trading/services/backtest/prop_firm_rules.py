"""Prop firm rule engine for compliance checking.

Enforces all prop firm evaluation rules during backtesting and live trading.
"""
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Optional
import pandas as pd


class PropFirmPlan(Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


@dataclass
class PropFirmConfig:
    max_daily_drawdown_pct: float = 0.05
    max_total_drawdown_pct: float = 0.10
    profit_target_pct: float = 0.10
    min_trading_days: int = 5
    max_trading_days: int = 30
    max_lot_size: float = 1.0
    min_lot_size: float = 0.01
    max_concurrent_positions: int = 2
    max_daily_trades: int = 10
    news_restricted_pairs: dict = field(default_factory=lambda: {
        'USD': ['NFP', 'CPI', 'FOMC', 'GDP', 'PMI'],
        'EUR': ['ECB', 'CPI', 'PMI', 'GDP'],
        'GBP': ['BOE', 'CPI', 'GDP', 'PMI'],
        'JPY': ['BOJ', 'CPI', 'GDP'],
    })
    news_restriction_minutes_before: int = 60
    news_restriction_minutes_after: int = 30
    news_event_schedule: dict = field(default_factory=dict)
    weekend_close_time: time = time(16, 0)
    weekend_gmt_offset: int = 0


@dataclass
class DailyStats:
    date: pd.Timestamp
    trades: int = 0
    pnl: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    max_drawdown: float = 0.0
    lot_size: float = 0.0
    position_count: int = 0


@dataclass
class PropFirmState:
    config: PropFirmConfig
    starting_balance: float
    current_balance: float
    peak_balance: float
    daily_stats: list = field(default_factory=list)
    open_positions: list = field(default_factory=list)
    trade_history: list = field(default_factory=list)
    violation_count: int = 0
    last_violation: Optional[str] = None

    @property
    def daily_drawdown(self) -> float:
        if not self.daily_stats:
            return 0.0
        return self.daily_stats[-1].max_drawdown

    @property
    def total_drawdown(self) -> float:
        return (self.peak_balance - self.current_balance) / self.peak_balance

    @property
    def profit_target_reached(self) -> bool:
        return (self.current_balance - self.starting_balance) / self.starting_balance >= self.config.profit_target_pct

    @property
    def trading_days_count(self) -> int:
        return len([d for d in self.daily_stats if d.trades > 0])

    def can_open_position(self, lot_size: float, pair: str, timestamp: pd.Timestamp) -> tuple[bool, str]:
        if self.profit_target_reached:
            return False, "Profit target reached"

        if len(self.open_positions) >= self.config.max_concurrent_positions:
            return False, "Max concurrent positions reached"

        daily_stats = self._get_current_day_stats(timestamp)
        if daily_stats.trades >= self.config.max_daily_trades:
            return False, "Max daily trades reached"

        if not self._check_news_restriction(pair, timestamp):
            return False, "News trading restriction active"

        if not self._check_weekend_restriction(timestamp):
            return False, "Weekend holding restriction"

        if lot_size < self.config.min_lot_size:
            return False, f"Lot size below minimum ({self.config.min_lot_size})"

        if lot_size > self.config.max_lot_size:
            return False, f"Lot size above maximum ({self.config.max_lot_size})"

        return True, "OK"

    def record_trade(self, pair: str, direction: str, lots: float, entry_price: float,
                     exit_price: float, pnl: float, entry_time: pd.Timestamp, exit_time: pd.Timestamp):
        self.trade_history.append({
            'pair': pair,
            'direction': direction,
            'lots': lots,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'holding_hours': (exit_time - entry_time).total_seconds() / 3600
        })

        self.current_balance += pnl
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance

        daily_stats = self._get_current_day_stats(exit_time)
        daily_stats.trades += 1
        daily_stats.pnl += pnl
        daily_stats.current_equity = self.current_balance

    def _get_current_day_stats(self, timestamp: pd.Timestamp) -> DailyStats:
        date = timestamp.normalize()
        for stats in self.daily_stats:
            if stats.date == date:
                return stats
        new_stats = DailyStats(date=date, peak_equity=self.peak_balance, current_equity=self.current_balance)
        self.daily_stats.append(new_stats)
        return new_stats

    def _check_news_restriction(self, pair: str, timestamp: pd.Timestamp) -> bool:
        schedule = self.config.news_event_schedule
        if not schedule:
            return True

        dt = timestamp.to_pydatetime()
        minutes_from_midnight = dt.hour * 60 + dt.minute
        day_of_week = dt.weekday()

        for currency, events in schedule.items():
            if currency not in pair:
                continue
            for event_time_str in events:
                parts = event_time_str.split(':')
                if len(parts) == 2:
                    event_hour, event_minute = int(parts[0]), int(parts[1])
                elif len(parts) == 3:
                    event_hour, event_minute = int(parts[0]), int(parts[1])
                    if int(parts[2]) != day_of_week:
                        continue
                else:
                    continue

                event_minutes = event_hour * 60 + event_minute
                restricted_start = event_minutes - self.config.news_restriction_minutes_before
                restricted_end = event_minutes + self.config.news_restriction_minutes_after

                if restricted_start <= minutes_from_midnight <= restricted_end:
                    return False

        return True

    def _check_weekend_restriction(self, timestamp: pd.Timestamp) -> bool:
        if timestamp.weekday() >= 5:
            return False
        return True


class PropFirmRuleEngine:
    def __init__(self, config: PropFirmConfig, starting_balance: float):
        self.state = PropFirmState(
            config=config,
            starting_balance=starting_balance,
            current_balance=starting_balance,
            peak_balance=starting_balance
        )

    def update_daily_drawdown(self, current_equity: float, timestamp: pd.Timestamp):
        daily_stats = self.state._get_current_day_stats(timestamp)
        daily_stats.current_equity = current_equity

        if current_equity > daily_stats.peak_equity:
            daily_stats.peak_equity = current_equity

        drawdown = (daily_stats.peak_equity - current_equity) / daily_stats.peak_equity
        daily_stats.max_drawdown = max(daily_stats.max_drawdown, drawdown)

        if drawdown > self.state.config.max_daily_drawdown_pct:
            self.state.violation_count += 1
            self.state.last_violation = f"Daily drawdown exceeded: {drawdown:.2%}"

    def check_drawdown_violation(self) -> bool:
        return self.state.total_drawdown > self.state.config.max_total_drawdown_pct

    def get_compliance_report(self) -> dict:
        return {
            'starting_balance': self.state.starting_balance,
            'current_balance': self.state.current_balance,
            'peak_balance': self.state.peak_balance,
            'total_pnl_pct': (self.state.current_balance - self.state.starting_balance) / self.state.starting_balance,
            'total_drawdown': self.state.total_drawdown,
            'daily_drawdown': self.state.daily_drawdown,
            'trading_days': self.state.trading_days_count,
            'total_trades': len(self.state.trade_history),
            'violation_count': self.state.violation_count,
            'last_violation': self.state.last_violation,
            'profit_target_reached': self.state.profit_target_reached,
        }
