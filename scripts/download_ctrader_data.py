#!/usr/bin/env python3
"""Download historical data from cTrader Open API for the Ayumi forex bot.

Downloads OHLCV bars for major pairs across multiple timeframes,
saving/ appending to CSV files in data/forex/historical/.
"""

import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from data.ctrader_client import CTraderHistoricalClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "GBPJPY", "XAUUSD"]
TIMEFRAMES = ["M15", "H1", "H4", "D1"]
START_DATE = "2026-01-01"
END_DATE = "2026-04-10"
OUTPUT_DIR = PROJECT_ROOT / "data" / "forex" / "historical"


def main():
    client_id = os.environ.get("CTRADER_OPENAPI_CLIENT_ID")
    client_secret = os.environ.get("CTRADER_OPENAPI_CLIENT_SECRET")
    account_id = os.environ.get("CTRADER_ACCOUNT")

    if not all([client_id, client_secret, account_id]):
        logger.error(
            "Missing CTRADER_OPENAPI_CLIENT_ID, CTRADER_OPENAPI_CLIENT_SECRET, or CTRADER_ACCOUNT in .env"
        )
        sys.exit(1)

    account_id = int(account_id)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = CTraderHistoricalClient(
        client_id=client_id,
        client_secret=client_secret,
        account_id=account_id,
    )

    total = len(PAIRS) * len(TIMEFRAMES)
    done = 0

    for pair in PAIRS:
        for tf in TIMEFRAMES:
            done += 1
            filename = f"{pair}_{tf}.csv"
            filepath = OUTPUT_DIR / filename
            logger.info(
                "[%d/%d] Downloading %s %s (%s → %s)",
                done,
                total,
                pair,
                tf,
                START_DATE,
                END_DATE,
            )

            try:
                client.download_and_save(
                    symbol=pair,
                    timeframe=tf,
                    start_date=START_DATE,
                    end_date=END_DATE,
                    output_path=str(filepath),
                    append=True,
                )
            except Exception as e:
                logger.error("Failed %s %s: %s", pair, tf, e)
                # Brief pause before next request
                time.sleep(1)

            time.sleep(0.5)

    logger.info("Done. Downloaded data for %d symbol/timeframe combinations.", done)


if __name__ == "__main__":
    main()
