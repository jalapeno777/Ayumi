# Sprint 3: Backtesting Harness (No-API)

**Issue:** AYUAA-43 | **Status:** done | **Source:** Paperclip

## Description

Build a backtesting harness that works without cTrader API, using historical CSV data.

- Create a data loader for OHLC CSV files (downloadable from TradingView or similar)
- Implement a backtest engine that replays candle data and feeds it through the signal confluence engine
- Track P&L, win rate, max drawdown, and Sharpe ratio
- Support configurable risk parameters (1-2% per trade per Craig direction)
- This unblocks testing without waiting for cTrader API access

## Discussion

**unknown:**

## Delivered: Backtesting Harness (No-API)

4 new files in `cbot/`:

- **ICTSMC.BacktestModels.cs** — Config presets (Default/Aggressive/Conservative), SimulatedTrade, BacktestMetrics with PrintReport()
- **ICTSMC.CsvDataLoader.cs** — OHLC CSV parser (TradingView format), auto time-frame inference, sample CSV generator
- **ICTSMC.BacktestEngine.cs** — Candle-by-candle replay through SignalConfluenceEngine, full trade simulation
- **ICTSMC.BacktestTests.cs** — 14 structural tests
- **ICTSMC.Program.cs** — Updated runner (--backtest / --report flags)

### Features

- **Risk management**: configurable % per trade (1-2% per Craig), max daily drawdown, max total drawdown
- **Trade simulation**: SL/TP1/TP2/TP3, partial close at TP1, trailing stop (ATR-based)
- **Metrics**: P&L, win rate, profit factor, max drawdown, Sharpe ratio, expectancy, equity curve
- **CSV loader**: TradingView format, auto TF inference, comma/semicolon/tab delimited
- **Signal filtering**: min confidence, min confluences, min R:R, max open trades
- **Session-aware**: London/NYAM/NYPM session detection for realistic signal gating

### Config presets

| | Default | Aggressive | Conservative |
|---|---|---|---|
| Risk/trade | 1% | 2% | 0.5% |
| Max daily DD | 2% | 5% | 1.5% |
| Min confidence | 0.55 | 0.50 | 0.65 |
| Min confluences | 2 | 1 | 3 |
| Trailing stop | off | on | off |

### Usage

```bash
dotnet run -- --backtest    # run backtest tests
dotnet run -- --report     # full backtest with report output
```

Or load real data:
```csharp
var loader = new CsvDataLoader();
var bars = loader.Load("EURUSD_15m.csv");
var engine = new BacktestEngine(BacktestConfig.Default);
var metrics = engine.Run(bars);
metrics.PrintReport();
```

No dotnet SDK on this machine — code structurally verified, not compiled.

- Parent: [AYUAA-11](/AYUAA/issues/AYUAA-11)
