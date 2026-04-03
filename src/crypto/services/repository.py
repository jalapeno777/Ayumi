from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class TradeRepository:
    def __init__(self, db_path: str | Path = "data/crypto/copy_trading.db"):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS providers (
                    provider_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    strategy TEXT DEFAULT '',
                    followers_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    lot_size REAL DEFAULT 0,
                    signal_time TEXT NOT NULL,
                    strategy_name TEXT DEFAULT '',
                    confluence_count INTEGER DEFAULT 0,
                    strength TEXT DEFAULT 'moderate',
                    FOREIGN KEY (provider_id) REFERENCES providers(provider_id)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id INTEGER NOT NULL,
                    follower_account_id TEXT NOT NULL,
                    allocation_usd REAL DEFAULT 0,
                    status TEXT DEFAULT 'open',
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    close_price REAL DEFAULT 0,
                    profit_loss REAL DEFAULT 0,
                    FOREIGN KEY (signal_id) REFERENCES signals(id)
                );

                CREATE INDEX IF NOT EXISTS idx_signals_provider ON signals(provider_id);
                CREATE INDEX IF NOT EXISTS idx_signals_time ON signals(signal_time);
                CREATE INDEX IF NOT EXISTS idx_trades_signal ON trades(signal_id);
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_follower ON trades(follower_account_id);
            """)

    def upsert_provider(
        self,
        provider_id: str,
        name: str,
        strategy: str = "",
        followers_count: int = 0,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO providers (provider_id, name, strategy, followers_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    name = excluded.name,
                    strategy = excluded.strategy,
                    followers_count = excluded.followers_count,
                    updated_at = excluded.updated_at
                """,
                (provider_id, name, strategy, followers_count, now, now),
            )

    def save_signal(self, signal: dict) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO signals
                    (provider_id, symbol, direction, entry_price, stop_loss, take_profit,
                     lot_size, signal_time, strategy_name, confluence_count, strength)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal["provider_id"],
                    signal["symbol"],
                    signal["direction"],
                    signal["entry_price"],
                    signal["stop_loss"],
                    signal["take_profit"],
                    signal.get("lot_size", 0),
                    signal["signal_time"],
                    signal.get("strategy_name", ""),
                    signal.get("confluence_count", 0),
                    signal.get("strength", "moderate"),
                ),
            )
            return cursor.lastrowid or 0

    def save_trade(self, trade: dict) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trades
                    (signal_id, follower_account_id, allocation_usd, status, opened_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    trade["signal_id"],
                    trade["follower_account_id"],
                    trade.get("allocation_usd", 0),
                    trade.get("status", "open"),
                    trade.get("opened_at", datetime.now(timezone.utc).isoformat()),
                ),
            )
            return cursor.lastrowid or 0

    def close_trade(self, trade_id: int, close_price: float, profit_loss: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE trades SET status = 'closed', closed_at = ?, close_price = ?, profit_loss = ?
                WHERE id = ?
                """,
                (now, close_price, profit_loss, trade_id),
            )

    def get_provider_stats(self, provider_id: str) -> dict:
        with self._connect() as conn:
            provider = conn.execute(
                "SELECT * FROM providers WHERE provider_id = ?", (provider_id,)
            ).fetchone()

            if not provider:
                return {}

            stats = conn.execute(
                """
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN profit_loss <= 0 THEN 1 ELSE 0 END) as losses,
                    COALESCE(SUM(profit_loss), 0) as total_profit,
                    AVG(
                        CASE
                            WHEN entry_price > 0 AND stop_loss > 0 AND take_profit > 0
                            THEN ABS(take_profit - entry_price) / ABS(entry_price - stop_loss)
                            ELSE 0
                        END
                    ) as avg_risk_reward
                FROM trades t
                JOIN signals s ON t.signal_id = s.id
                WHERE s.provider_id = ? AND t.status = 'closed'
                """,
                (provider_id,),
            ).fetchone()

            total = stats["total_trades"] or 0
            wins = stats["wins"] or 0
            return {
                "provider_id": provider_id,
                "provider_name": provider["name"],
                "strategy": provider["strategy"],
                "total_trades": total,
                "wins": wins,
                "losses": stats["losses"] or 0,
                "total_profit": round(stats["total_profit"] or 0, 2),
                "avg_risk_reward": round(stats["avg_risk_reward"] or 0, 2),
                "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
                "followers_count": provider["followers_count"],
            }

    def get_leaderboard(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    p.provider_id,
                    p.name as provider_name,
                    p.strategy,
                    p.followers_count,
                    COALESCE(COUNT(t.id), 0) as total_trades,
                    COALESCE(SUM(CASE WHEN t.profit_loss > 0 THEN 1 ELSE 0 END), 0) as wins,
                    COALESCE(SUM(t.profit_loss), 0) as total_profit
                FROM providers p
                LEFT JOIN signals s ON s.provider_id = p.provider_id
                LEFT JOIN trades t ON t.signal_id = s.id AND t.status = 'closed'
                GROUP BY p.provider_id
                ORDER BY total_profit DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            results = []
            for row in rows:
                total = row["total_trades"]
                wins = row["wins"]
                results.append({
                    "provider_id": row["provider_id"],
                    "provider_name": row["provider_name"],
                    "strategy": row["strategy"],
                    "total_trades": total,
                    "wins": wins,
                    "losses": total - wins,
                    "total_profit": round(row["total_profit"], 2),
                    "win_rate": round(wins / total * 100, 1) if total > 0 else 0.0,
                    "followers_count": row["followers_count"],
                })
            return results

    def get_recent_signals(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*, p.name as provider_name
                FROM signals s
                JOIN providers p ON s.provider_id = p.provider_id
                ORDER BY s.signal_time DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
