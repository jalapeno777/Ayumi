using System;

namespace ICTSMC
{
    public class Program
    {
        public static void Main(string[] args)
        {
            Console.WriteLine("ICT/SMC Trading System - Test Runner\n");

            if (args.Length > 0 && args[0] == "--backtest")
            {
                BacktestTests.RunAll();
            }
            else if (args.Length > 0 && args[0] == "--report")
            {
                RunBacktestReport();
            }
            else
            {
                ConfluenceEngineTests.RunAll();
                Console.WriteLine();
                BacktestTests.RunAll();
            }
        }

        private static void RunBacktestReport()
        {
            Console.WriteLine("Running full backtest with sample data...\n");

            var bars = MockDataGenerator.GenerateBullishTrend(200);
            var engine = new BacktestEngine(BacktestConfig.Default);
            var metrics = engine.Run(bars);
            metrics.PrintReport();
        }
    }
}
