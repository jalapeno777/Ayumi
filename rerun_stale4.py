"""Re-run the 4 stale-data streams on freshest duckdb-exported CSVs (data end 2026-07-10).
Method mirrors summary.md: run_strategy_walk_forward(n_windows=5, train=0.7, val=0.15, overlap=0.2)."""
import sys, json, statistics
sys.path.insert(0, "/tmp/ayumi-wf-satsuki/src/forex-bot")
import pandas as pd
from datetime import timezone
from strategies.srmr_plus import SRMRPlusStrategy, SRMRPlusConfig
from backtest.walk_forward_runner import run_strategy_walk_forward
from backtest.engine import Bar

REPORT = "/home/TacoPants/projects/Ayumi/reports/srmr-wf-revalidation-2026-09-07"
SPREAD = {"EURUSD": 2.0, "XAUUSD": 40.0}

STREAMS = [
    ("srmr_eurusd_h1", "EURUSD", "H1"),
    ("srmr_eurusd_h4", "EURUSD", "H4"),
    ("srmr_xauusd_h1", "XAUUSD", "H1"),
    ("srmr_xauusd_h4", "XAUUSD", "H4"),
]

import yaml
cfg = yaml.safe_load(open("/home/TacoPants/projects/Ayumi/src/forex-bot/config/strategies.yaml"))
def find(o):
    if isinstance(o, dict):
        if "strategies" in o and isinstance(o["strategies"], list): return o["strategies"]
        for v in o.values():
            r = find(v)
            if r: return r
PARAMS = {e["id"]: e for e in find(cfg)}

def load_bars(path):
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    if "date" in df.columns and "timestamp" not in df.columns:
        df = df.rename(columns={"date": "timestamp"})
    bars = []
    for _, row in df.iterrows():
        dt = pd.to_datetime(row["timestamp"])
        if dt.tz is None: dt = dt.tz_localize("UTC")
        bars.append(Bar(time=dt, open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]), volume=float(row.get("volume", 0))))
    return bars

for sid, sym, tf in STREAMS:
    params = dict(PARAMS[sid]["params"])
    params.pop("symbol", None); params.pop("dxy_overlay", False)
    conf = SRMRPlusConfig(**params)
    bars = load_bars(f"{REPORT}/data/{sym}_{tf}.csv")
    res = run_strategy_walk_forward(
        bars=bars,
        strategy_factory=lambda train_bars, c=conf, n=sid: SRMRPlusStrategy(config=c, name=n),
        pair=sym, n_windows=5, train_ratio=0.7, val_ratio=0.15, overlap_ratio=0.2,
        initial_balance=10000, spread_pips=SPREAD[sym], commission_per_lot=3.5,
        min_confidence=0.40,
    )
    wins = [w for w in res.per_window if w.passed]
    out = {
        "stream_id": sid, "symbol": sym, "timeframe": tf,
        "data_end_date": str(bars[-1].time), "data_source": "duckdb-export",
        "n_windows": len(res.per_window), "windows_passed": len(wins),
        "mean_win_rate": statistics.mean(w.win_rate for w in res.per_window),
        "mean_profit_factor": statistics.mean(w.profit_factor for w in res.per_window),
        "mean_sharpe": statistics.mean(w.sharpe_ratio for w in res.per_window),
        "mean_trade_count": statistics.mean(w.trade_count for w in res.per_window),
        "windows": [{k: getattr(w, k) for k in ("window_idx","win_rate","profit_factor","max_drawdown","sharpe_ratio","trade_count","total_pnl","passed")} for w in res.per_window],
    }
    with open(f"{REPORT}/{sid}_fresh.jsonl", "w") as f:
        f.write(json.dumps(out, default=str))
    print(sid, "WP", out["windows_passed"], "PF", round(out["mean_profit_factor"],3), "WR", round(out["mean_win_rate"],4), "trades", out["mean_trade_count"])
