import os
import sys
import json
import argparse

ml_dir = os.path.dirname(os.path.abspath(__file__))
forex_bot_dir = os.path.dirname(ml_dir)
sys.path.insert(0, forex_bot_dir)

from ml.train_model import run_full_pipeline


def parse_args():
    parser = argparse.ArgumentParser(description="ML Signal Filter — Training Pipeline")
    parser.add_argument("--source", choices=["csv", "db"], default="csv",
                        help="Data source: csv (default) or db (SQLite)")
    parser.add_argument("--db-path", default=None,
                        help="Path to forex.db (default: data/forex/forex.db or FOREX_DB_PATH env var)")
    parser.add_argument("--symbols", nargs="+", default=["EURUSD", "GBPUSD"],
                        help="Symbols to train on")
    parser.add_argument("--timeframe", default="H1", help="Primary timeframe")
    parser.add_argument("--max-holding-bars", type=int, default=50,
                        help="Max bars a trade can be held")
    parser.add_argument("--n-folds", type=int, default=5,
                        help="Number of walk-forward folds")
    return parser.parse_args()


def main():
    args = parse_args()
    project_root = os.path.dirname(os.path.dirname(forex_bot_dir))
    data_dir = os.path.join(project_root, "data", "forex")
    model_dir = os.path.join(data_dir, "models")

    symbols = args.symbols

    print("=" * 60)
    print("ML Signal Filter — Training Pipeline")
    print("=" * 60)
    print(f"\nData dir:  {data_dir}")
    print(f"Model dir: {model_dir}")
    print(f"Source:    {args.source}")
    if args.source == "db":
        print(f"DB path:   {args.db_path or 'default'}")
    print(f"Symbols:   {symbols}")
    print()

    results = run_full_pipeline(
        symbols=symbols,
        data_dir=data_dir,
        output_dir=model_dir,
        timeframe=args.timeframe,
        max_holding_bars=args.max_holding_bars,
        n_folds=args.n_folds,
        source=args.source,
        db_path=args.db_path,
    )

    if "error" in results and "folds" not in results:
        print(f"\nERROR: {results['error']}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Walk-Forward Validation Results")
    print("=" * 60)

    if "summary" in results:
        summary = results["summary"]
        print(f"\nCompleted folds: {summary.get('n_folds_completed', 0)}")
        print(f"Avg accuracy:            {summary.get('avg_accuracy', 'N/A')}")
        print(f"Avg precision:           {summary.get('avg_precision', 'N/A')}")
        print(f"Avg recall:              {summary.get('avg_recall', 'N/A')}")
        print(f"Avg F1:                  {summary.get('avg_f1', 'N/A')}")
        print(f"\n--- Default Threshold (0.5) ---")
        print(f"Baseline win rate:       {summary.get('avg_baseline_win_rate', 'N/A')}%")
        print(f"Filtered win rate:       {summary.get('avg_filtered_win_rate', 'N/A')}%")
        print(f"Avg filter rate:         {summary.get('avg_filter_rate', 'N/A')}")
        print(f"\n--- Optimized Threshold ---")
        print(f"Avg opt threshold:       {summary.get('avg_opt_threshold', 'N/A')}")
        print(f"Avg opt win rate:        {summary.get('avg_opt_win_rate', 'N/A')}%")
        print(f"Avg opt PF:              {summary.get('avg_opt_profit_factor', 'N/A')}")
        print(f"Avg baseline PF:         {summary.get('avg_baseline_profit_factor', 'N/A')}")
        print(f"Avg opt total PnL:       {summary.get('avg_opt_total_pnl', 'N/A')}")
        print(f"Avg opt filter rate:     {summary.get('avg_opt_filter_rate', 'N/A')}")
        print(f"Avg opt trade count:     {summary.get('avg_opt_trade_count', 'N/A')}")

    if "folds" in results:
        print("\n--- Per-Fold Details ---")
        for fold in results["folds"]:
            print(f"\nFold {fold['fold']}: train={fold['train_size']}, test={fold['test_size']}")
            print(f"  Default: WR {fold['baseline_win_rate']}% -> {fold['filtered_win_rate']}% "
                  f"({fold['n_filtered_trades']}/{fold['n_total_trades']} trades), "
                  f"PF {fold['baseline_profit_factor']} -> {fold['filtered_profit_factor']}")
            print(f"  Optimized: threshold={fold.get('opt_threshold', 'N/A')}, "
                  f"WR={fold.get('opt_win_rate', 'N/A')}%, "
                  f"PF={fold.get('opt_profit_factor', 'N/A')}, "
                  f"trades={fold.get('opt_trade_count', 'N/A')}")

    if "final_model" in results:
        print(f"\nFinal model params: {results['final_params']}")
        print(f"Model saved to: {results['model_path']}")

        if results["folds"]:
            last_fold = results["folds"][-1]
            if "feature_importance" in last_fold:
                print("\nTop 10 Feature Importance:")
                for feat, imp in list(last_fold["feature_importance"].items())[:10]:
                    print(f"  {feat:25s} {imp:.4f}")

    report_path = os.path.join(model_dir, "training_report.json")
    report = {
        "summary": results.get("summary", {}),
        "folds": results.get("folds", []),
        "final_params": results.get("final_params"),
    }
    if "model_path" in results:
        report["model_path"] = results["model_path"]

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nTraining report saved to: {report_path}")


if __name__ == "__main__":
    main()
