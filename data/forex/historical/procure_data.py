#!/usr/bin/env python3
"""Download real historical forex M1 data from HistData.com and resample.

Source: HistData.com MetaTrader M1 bid data
Format:  YYYY.MM.DD,HH:MM,open,high,low,close,volume
Output:  CsvDataLoader-compatible CSV (Date,Open,High,Low,Close,Volume)
"""

import io
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import urllib.request
import urllib.parse

OUTPUT_DIR = Path("/home/TacoPants/projects/Ayumi/worktrees/junior-dev-1/data/forex/historical")
BASE_URL = "https://www.histdata.com"

PAIRS = ["EURUSD", "GBPUSD", "GBPJPY", "USDJPY", "XAUUSD"]
YEARS = [2023, 2024, 2025]

OUTPUT_TIMEFRAMES = ["M15", "H1", "H4", "D1"]


def get_token_and_download(pair: str, year: int) -> bytes:
    """Fetch yearly page, extract token, POST to download zip."""
    url = f"{BASE_URL}/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes/{pair.lower()}/{year}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=30)
    html = resp.read().decode()

    forms = re.findall(r'<form[^>]*action="(/get\.php)"[^>]*>(.*?)</form>', html, re.DOTALL)
    params = {}
    for action, body in forms:
        inputs = re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', body)
        for name, val in inputs:
            params[name] = val

    if "tk" not in params:
        raise ValueError(f"No download token found for {pair} {year}")

    data = urllib.parse.urlencode({
        "tk": params["tk"],
        "date": params.get("date", str(year)),
        "datemonth": params.get("datemonth", str(year)),
        "platform": params.get("platform", "MT"),
        "timeframe": params.get("timeframe", "M1"),
        "fxpair": params.get("fxpair", pair),
    }).encode()

    req2 = urllib.request.Request(f"{BASE_URL}/get.php", data=data, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": f"{BASE_URL}/download-free-forex-historical-data/",
    })
    resp2 = urllib.request.urlopen(req2, timeout=120)
    return resp2.read()


def parse_histdata_csv(csv_bytes: bytes) -> pd.DataFrame:
    """Parse HistData CSV: YYYY.MM.DD,HH:MM,open,high,low,close,volume"""
    lines = csv_bytes.decode("utf-8", errors="ignore").strip().split("\n")
    records = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#") or line.startswith("local_time"):
            continue
        parts = line.split(",")
        if len(parts) < 7:
            continue
        try:
            dt = pd.to_datetime(f"{parts[0]} {parts[1]}", format="%Y.%m.%d %H:%M", errors="coerce")
            if pd.isna(dt):
                continue
            records.append({
                "timestamp": dt,
                "Open": float(parts[2]),
                "High": float(parts[3]),
                "Low": float(parts[4]),
                "Close": float(parts[5]),
                "Volume": int(float(parts[6])) if parts[6].strip() else 0,
            })
        except (ValueError, IndexError):
            continue

    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df = df.drop_duplicates(subset=["timestamp"]).set_index("timestamp").sort_index()
    return df


def resample_df(df: pd.DataFrame, tf_name: str) -> pd.DataFrame:
    if df.empty:
        return df
    tf_map = {"M15": "15min", "H1": "1h", "H4": "4h", "D1": "1D"}
    resampled = df.resample(tf_map[tf_name], closed="left", label="left").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    })
    resampled = resampled.dropna(subset=["Open", "High", "Low", "Close"])
    return resampled


def write_csv(df: pd.DataFrame, filepath: Path) -> int:
    csv_df = pd.DataFrame({
        "Date": df.index.strftime("%Y-%m-%d %H:%M"),
        "Open": df["Open"].round(5),
        "High": df["High"].round(5),
        "Low": df["Low"].round(5),
        "Close": df["Close"].round(5),
        "Volume": df["Volume"].astype(int),
    })
    csv_df.to_csv(filepath, index=False)
    return len(csv_df)


def gap_analysis(df: pd.DataFrame, tf_name: str) -> dict:
    if df.empty:
        return {"total_gaps": 0, "weekend_gaps": 0, "intraday_gaps": 0}
    tf_minutes = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}
    minutes = tf_minutes.get(tf_name, 15)
    gaps = []
    for i in range(1, min(len(df), 100000)):
        diff = (df.index[i] - df.index[i - 1]).total_seconds() / 60
        if diff > minutes * 1.5:
            gaps.append(diff)
    weekend = sum(1 for g in gaps if g > 1000)
    intraday = sum(1 for g in gaps if g <= 1000)
    return {"total_gaps": len(gaps), "weekend_gaps": weekend, "intraday_gaps": intraday}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_reports = []

    for pair in PAIRS:
        print(f"\n{'='*60}")
        print(f"  {pair}")
        print(f"{'='*60}")

        m1_combined = pd.DataFrame()

        for year in YEARS:
            label = f"{pair} {year}"
            print(f"  Downloading {label}...", end="", flush=True)

            try:
                zip_data = get_token_and_download(pair, year)
            except Exception as e:
                print(f" FAIL: {e}")
                time.sleep(2)
                continue

            try:
                with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                    csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
                    csv_bytes = zf.read(csv_names[0])
            except Exception as e:
                print(f" UNZIP FAIL: {e}")
                continue

            df = parse_histdata_csv(csv_bytes)
            if df.empty:
                print(" PARSE EMPTY")
                continue

            m1_combined = pd.concat([m1_combined, df])
            print(f" {len(df)} M1 bars (running total: {len(m1_combined)})")
            time.sleep(1)

        if m1_combined.empty:
            print(f"  {pair}: No data collected")
            continue

        m1_combined = m1_combined[~m1_combined.index.duplicated(keep="first")]
        m1_combined = m1_combined.sort_index()
        print(f"\n  {pair} total: {len(m1_combined)} M1 bars")
        print(f"  Range: {m1_combined.index.min()} to {m1_combined.index.max()}")

        for tf_name in OUTPUT_TIMEFRAMES:
            df = resample_df(m1_combined, tf_name)
            if df.empty:
                continue

            filepath = OUTPUT_DIR / f"{pair}_{tf_name}.csv"
            rows = write_csv(df, filepath)
            gaps = gap_analysis(df, tf_name)

            report = {
                "pair": pair, "tf": tf_name, "bars": rows,
                "start": str(df.index.min()), "end": str(df.index.max()),
                **gaps,
            }
            all_reports.append(report)
            print(f"    {tf_name}: {rows:>7d} bars  gaps={gaps['total_gaps']:>4d} "
                  f"(weekend={gaps['weekend_gaps']}, intraday={gaps['intraday_gaps']})")

    report_path = OUTPUT_DIR / "quality_report.txt"
    with open(report_path, "w") as f:
        f.write("FOREX DATA QUALITY REPORT\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Source: HistData.com (MetaTrader M1 bid data)\n")
        f.write(f"Date Range: 2023-01 to 2025-12\n")
        f.write(f"Instruments: EURUSD, GBPUSD\n")
        f.write(f"Method: M1 yearly downloads, resampled to M15/H1/H4/D1\n\n")

        f.write("FILE INVENTORY\n")
        f.write("-" * 60 + "\n")
        for r in all_reports:
            f.write(f"  {r['pair']}_{r['tf']}.csv  ({r['bars']} bars)\n")

        f.write("\nGAP ANALYSIS\n")
        f.write("-" * 60 + "\n")
        for r in all_reports:
            f.write(f"  {r['pair']:8s} {r['tf']:4s}  bars={r['bars']:>7d}  "
                    f"gaps={r['total_gaps']:>4d}  "
                    f"(weekend={r['weekend_gaps']}, intraday={r['intraday_gaps']})\n")
            f.write(f"           range: {r['start']} to {r['end']}\n")

        f.write("\nNOTES\n")
        f.write("-" * 60 + "\n")
        f.write("- Data source: HistData.com MetaTrader bid prices\n")
        f.write("- Weekend gaps (Fri close to Sun/Mon open) are expected\n")
        f.write("- Intraday gaps may occur during low-liquidity sessions\n")
        f.write("- Volume field is tick volume (often 0 in HistData)\n")
        f.write("- CSV format: Date,Open,High,Low,Close,Volume (yyyy-MM-dd HH:mm)\n")
        f.write("- Compatible with ICTSMC.CsvDataLoader\n")

    print(f"\n{'='*60}")
    print(f"  DONE - {len(all_reports)} files generated")
    print(f"  Report: {report_path}")
    print(f"  Files:  {OUTPUT_DIR}/")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
