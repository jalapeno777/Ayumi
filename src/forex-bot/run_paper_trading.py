#!/usr/bin/env python3
"""CLI entry point for the paper trading orchestrator."""

import logging
import sys

sys.path.insert(0, "src/forex-bot")
sys.path.insert(0, "src")

from adapters.ctrader.paper_orchestrator import run_paper_trading


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 64)
    print("  LEAN BLEND PAPER TRADING — 5 Strategy Portfolio")
    print("=" * 64)

    summary = run_paper_trading()

    if summary["total_pnl"] < 0:
        print(f"\nWARNING: Net loss of ${summary['total_pnl']:,.2f}")
        sys.exit(1)

    status = "✅ FTMO PASS" if summary["ftmo_pass"] else "⚠️ FTMO RISK"
    print(f"\n{status} — Net profit of ${summary['total_pnl']:,.2f}")
    sys.exit(0)


if __name__ == "__main__":
    main()
