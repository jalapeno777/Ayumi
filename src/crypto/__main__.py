from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from crypto.bot.copy_trading_bot import CopyTradingBot
from crypto.bot.dashboard import DashboardServer
from crypto.services.repository import TradeRepository


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    repo = TradeRepository(args.db_path)
    from crypto.bot.api import create_app

    app = create_app(repo)
    print(f"Starting API server on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_run_dashboard(args: argparse.Namespace) -> None:
    repo = TradeRepository(args.db_path)
    server = DashboardServer(repo=repo, host=args.host, port=args.port)
    print(f"Starting dashboard on http://{args.host}:{args.port}")
    server.run()


def cmd_register(args: argparse.Namespace) -> None:
    repo = TradeRepository(args.db_path)
    repo.upsert_provider(args.provider_id, args.name, args.strategy or "", 0)
    print(f"Registered provider: {args.name} ({args.provider_id})")


def cmd_leaderboard(args: argparse.Namespace) -> None:
    repo = TradeRepository(args.db_path)
    lb = repo.get_leaderboard(args.limit)
    if not lb:
        print("No provider data yet.")
        return
    for i, p in enumerate(lb, 1):
        print(
            f"#{i} {p['provider_name']} | "
            f"WR: {p['win_rate']}% | "
            f"P&L: ${p['total_profit']} | "
            f"Trades: {p['total_trades']} | "
            f"Followers: {p['followers_count']}"
        )


def cmd_recent(args: argparse.Namespace) -> None:
    repo = TradeRepository(args.db_path)
    signals = repo.get_recent_signals(args.limit)
    if not signals:
        print("No signals yet.")
        return
    for s in signals:
        print(
            f"{s['signal_time']} | {s['provider_name']} | "
            f"{s['symbol']} {s['direction'].upper()} | "
            f"Entry: {s['entry_price']} SL: {s['stop_loss']} TP: {s['take_profit']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ayumi-copy",
        description="Ayumi Copy Trading Platform CLI",
    )
    parser.add_argument(
        "--db-path",
        default="data/crypto/copy_trading.db",
        help="Path to SQLite database (default: data/crypto/copy_trading.db)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    dashboard_p = sub.add_parser("serve", help="Start the API server (FastAPI + dashboard)")
    dashboard_p.add_argument("--host", default="0.0.0.0")
    dashboard_p.add_argument("--port", type=int, default=8080)

    register_p = sub.add_parser("register", help="Register a strategy provider")
    register_p.add_argument("provider_id", help="Unique provider identifier")
    register_p.add_argument("name", help="Display name")
    register_p.add_argument("--strategy", default="", help="Strategy description")

    sub.add_parser("leaderboard", help="Print provider leaderboard")
    sub.add_parser("recent", help="Print recent signals")

    for p in [sub.choices.get("leaderboard"), sub.choices.get("recent")]:
        if p:
            p.add_argument("--limit", type=int, default=10)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    Path(args.db_path).parent.mkdir(parents=True, exist_ok=True)

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "register":
        cmd_register(args)
    elif args.command == "leaderboard":
        cmd_leaderboard(args)
    elif args.command == "recent":
        cmd_recent(args)


if __name__ == "__main__":
    main()
