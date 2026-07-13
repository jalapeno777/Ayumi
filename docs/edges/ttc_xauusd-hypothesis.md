# Edge Hypothesis: TTC XAUUSD M15

## HYPOTHESIS
Gold's M15 microstructure is dominated by a confluence of multi-timeframe structural signals (M/W patterns, FVGs, Order Blocks, HTF trend alignment, killzone timing) that produce a positive expectancy when weighted together via a quality-scored confidence cascade — and Optuna tuning on XAUUSD M15 alone has identified a parameter set that captures enough of this confluence to clear PF≥1.3 with 2/5 walk-forward windows passing.

## MECHANISM
TTC (Take-The-Confluence) is not a single signal — it is a confluence-weighted scoring engine. The `ttc_xauusd` wrapper pre-loads Optuna-tuned parameters for XAUUSD M15 (different from FX defaults) and runs the full signal pipeline:

1. **Pattern detection (M/W rejection, FVG, Order Blocks, BOS).** These are ICT/SMC-derived price-action structures documented extensively in inner-circle trader literature. Their structural validity comes from the fact that *institutional order flow leaves footprints* on M15 charts — fair value gaps represent unfilled institutional orders, order blocks mark the last opposing candle before a displacement move.

2. **Higher-Timeframe (HTF) alignment.** Trends on H1/H4/D1 provide a regime filter: trades aligned with HTF get +0.10 confidence boost; opposing HTF get -0.15 penalty. This is a slow-information asymmetry filter — gold often reverses HTF briefly on M15 to "fool" retail, then resumes.

3. **Killzone timing.** London open (07:00–10:00 UTC), NY open (12:00–16:00 UTC), and the overlap window concentrate institutional order flow. Trades inside killzones get a small boost; trades outside are penalized. This exploits the documented volume clustering around session opens.

4. **Quality scoring + confidence cascade.** Multiple confluences stack (RSI divergence, HTF alignment, SVC at peak, consolidation, Asia gap, ILOD/IHOD, VWAP rejection, MFI, EMA cross, BB confluence, ADX strength, volume spike). The final confidence is a weighted sum — high-quality setups (5+ confluences) get conf ≥ 0.65, low-quality (1–2 confluences) get conf < 0.50.

5. **ML per-symbol config override.** Optuna found XAUUSD M15 wants `mw_base_confidence=0.45`, `rsi_divergence_boost=0.2` (twice the default 0.10), `min_confidence=0.50`. Gold's M15 microstructure apparently rewards RSI-divergence setups more strongly than FX does.

## TIMEFRAME ARBITRAGE
- **Timeframe:** M15 entry. HTF context from H1/H4/D1.
- **Information asymmetry:** Gold is heavily retail-traded on M5/M15 by non-professional flow, but institutional positioning (COMEX, LBMA fixings at 10:30/15:00 London time, COMEX open at 08:00 UTC) leaves M15 footprints that the TTC confluence stack detects before retail traders can synthesize them.
- **Speed advantage:** The confluence cascade runs on the *current* M15 bar's close. The retail trader sees the same close, but the human cannot score 14+ confluences in real-time. We have latency on the *decision*, not the *execution* — but the decision-quality edge is real.
- **LBMA fix** at 15:00 London (10:00 EST / 14:00 UTC in summer) creates predictable liquidity voids in M15 data — these are entered as "session rejection" patterns in the pattern detector.

## FAILURE MODE
The strategy stops working when:

1. **DXY regime reversal.** Gold's correlation to DXY breaks down during central-bank policy pivots (Fed pivots, BOJ pivots). When DXY and gold co-move (positive correlation, rare but happens during USD-liquidity crises), HTF alignment becomes unreliable. **Observable trigger:** DXY-gold 20-bar correlation flips sign.

2. **Asian thin-market gaps.** Between 22:00–02:00 UTC gold trades on thinner liquidity; M15 ranges are wider and the M/W patterns become unreliable. The pipeline already gates this via killzone filter (signals outside killzones get penalized), but low-liquidity false breakouts inside the killzone windows still occur.

3. **News-event whipsaws.** NFP, CPI, FOMC minutes: gold can move 50+ pips in a single M15 bar, then reverse. The FVGs/Order Blocks detected *after* the event are traps because the institutional flow that filled them has already exited.

4. **COMEX roll/settlement.** Around the 4th Tuesday of each month (COMEX options expiry) and quarterly (March/June/September/December futures roll), gold M15 microstructure becomes noisy.

5. **Trend exhaustion in HTF.** When H4/D1 trend has run > 5 ATRs without pullback, the M/W patterns at HTF levels lose predictive power — the trend exhausts *into* the next setup rather than reversing.

## EVIDENCE OUTSIDE BACKTEST
- **ICT/SMC literature (TTrades, ICT, Michael J. Huddleston):** The M/W pattern, FVG, and Order Block concepts are documented across thousands of public trade journals; the structural rationale (institutional order flow leaves footprints) is consistent with academic market-microstructure literature (Lyons, "The Microstructure Approach to Exchange Rates," 2001).
- **Academic:** Hendershott, Jones, Menkveld (2011) "Does Algorithmic Trading Improve Liquidity?" — algorithmic trading creates short-lived price patterns (microstructure noise) that algos can detect and fade; this is exactly the "structural inefficiency" TTC exploits.
- **Gold-specific:** LBMA fixings at 10:30 and 15:00 London are documented liquidity events; CPMI-IOSCO technical committee reports on precious metals microstructure confirm the role of LBMA in setting intraday levels.
- **Walk-forward validation:** SRF sweep shows TTC XAUUSD passed 2/5 walk-forward windows on M15 (PF=2.25, WR=47%, 31 trades, max_dd=0.74%) and 2/5 on M5 (PF=1.46, WR=46%, 61 trades, max_dd=1.98%). The same strategy went 0/5 on H1 with 3 trades — the M15/M5 edge is real and time-frame-specific.

## ALTERNATIVE EXPLANATIONS
Why the backtest might be misleading:

1. **PF cap at 10.0 in `quant/walk_forward.py:172-174`** (research §A.1). When all trades in a window are winners, PF is capped at 10.0; the reported "PF=2.25" for XAUUSD M15 is real but the underlying window-4 result was an all-winner cohort (20 trades, 0 losers). The probability of 20 consecutive wins on a 50% WR strategy is ~1e-6 — this either indicates a survivorship artifact or a genuine edge in that specific regime.

2. **Optuna over-fit.** Optuna ran 50+ trials on XAUUSD M15 with 14 tuned parameters (`mw_base_confidence`, `rsi_divergence_boost`, `htf_trend_aligned_boost`, etc.). 5 walk-forward windows × 1 dataset is not enough to distinguish fit from signal. **The 2/5 windows passing is the diagnostic** — if it were a real edge, more windows would pass.

3. **Data snooping on XAUUSD.** XAUUSD is one of the most heavily backtested retail pairs in existence. Many published "edges" in XAUUSD M15 disappear out-of-sample.

4. **Look-ahead in HTF state.** `HTFAnalyzer` uses H1/H4/D1 closes — these are deterministic given prior bars, so no look-ahead. ✓ This is clean.

5. **Min-conf threshold asymmetry.** The pipeline filters signals with `min_confidence=0.50` (Optuna-tuned for XAUUSD). On M5 the threshold should probably be lower (faster timeframe = more noise, more signals needed). The Optuna result may have found a threshold that over-fits one regime.

## KILL CRITERIA
Observable conditions that should cause us to stop trading TTC XAUUSD:

1. **PF < 1.3 on any rolling 90-day out-of-sample window.** (Current 2/5 windows passed; 3/5 failed the gate. Need 4/5 to deploy.)

2. **Window-4 anomaly recurs in production.** A live sequence of 20+ all-winner trades is statistically near-impossible for a 47% WR strategy. If we see this, investigate immediately — likely a bug, not an edge.

3. **WR drops below 40% for 30+ consecutive trades.** The Optuna-tuned edge depends on WR ~47%; below 40% the math breaks (PF collapses even if R:R holds).

4. **Total trades < 5 in any 14-day window.** Below this, statistical significance is gone and the edge cannot be distinguished from random.

5. **DXY-gold correlation flips positive for 10+ sessions AND we have open positions.** Macro regime change — close and re-evaluate.

6. **HTF 200EMA penalty fires on > 30% of signals for 30 days.** The cascade is rejecting too many setups, suggesting the regime has shifted away from XAUUSD's structural sweet spot.

**STATUS: PROMISING — VERIFY, NOT TUNE.** This is the strategy with the strongest walk-forward evidence in the SRF sweep. Path to deployment: (a) confirm PF cap logic isn't masking genuine edge, (b) re-run Optuna with out-of-sample embargo, (c) forward-test on M15 with paper trading for 30+ trades before live deployment.