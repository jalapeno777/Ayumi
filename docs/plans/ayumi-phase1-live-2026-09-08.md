# Ayumi Phase 1 — LIVE (2026-09-08, ~12:41 EDT)

**Status:** Phase 1 shipped. Blend forward test restarted on merged main with D5 risk envelope. This supersedes the 2026-09-07 handoff.

## Live process (verified 16:43 UTC / 12:43 EDT)
- systemd unit `ayumi-forward-test.service`, ACTIVE, user TacoPants
- Exec: `.venv/bin/python scripts/launch_blend_forward_test.py --symbols XAUUSD --only "SRMR+" --live`
- Broker: authenticated (account 46877902), spot feed connected, ticks flowing (~2.7 tps)
- Balance **$10,262.45** (+2.62% lifetime); FTMO peak reconciled **$10,415.81**; account DD from peak ≈1.47%
- 0 open positions; sizer/broker in sync; eval_errors=0
- FTMOGuard active: dd_reduce 8%, dd_freeze 9%, daily_loss 3%, kill_switch wired

## What shipped today (main, Rin-cleared)
| Commit | Card | What |
|---|---|---|
| 2f133d37 | 09e99147 | Kill-switch harness enable (flip class default pre-construction + runtime split-state guard) |
| 0c7a6724 | 047cd91d | Unit-mix fix: `_resolve_contract_size()` per-symbol lookup + paper-trader uses orchestrator volume (killed the 1000× P&L distortion) |
| 5900108c | — | **D5 envelope**: risk_per_trade_pct 0.0025 ($25/trade), daily_risk_cap_pct 0.02 ($200 worst day), 3 sniper + 5 swarm slots |

Harness re-run #3 (reports/blend-harness-2026-09-08/): 5/6 AC PASS. Final balance $9,944.97, max DD $55.03, SL-close P&L −$54.96 (correct class), positions close, kill switch blocks entries.

## Decisions locked (Craig)
- **D5 risk envelope** + single bundled restart — approved 12:39 EDT, executed.
- **Asia window = UTC 00:00–07:00, final 30 min excluded** (card cba5d148). Doc reconciliation pending on that card; unblocks directional-lock sweep d996375c.

## Incident + recovery (16:30–16:41 UTC)
Harness re-run #3 (run as root) wrote a **fake global kill + test balance into LIVE state files** (root-owned 0600). First restart crashed (PermissionError); quarantine + chown + clean restart. Poisoned state preserved in `archive/poisoned-state-20260908/`. **Root cause carded urgent: 758273a7** — harness must use isolated state dirs + ownership guard. Do NOT run the harness again before that lands.

## Open Ayumi queue (workboard)
| Card | Title | Priority |
|---|---|---|
| 758273a7 | Harness writes fake kill/risk state into live paths — test isolation | **urgent** |
| 644c565b | Harness eval-loop halt on global kill (AC4 partial) | normal |
| 75b24f98 | Close-path fidelity: SL fills at level + pre-trade FTMO ordering | normal |
| 26c1209a | h4_bars AttributeError — KZ leg possibly dead in blend | normal |
| cba5d148 | Asia-window UTC freeze execution (decision made, docs pending) | urgent |
| e3df6a04 | XAU Asia-qualification basis (ATR-normalized candidate) — blocks port validation | high |
| d996375c | Directional-lock sweep TTC (after Asia freeze) | normal |
| 46b631ab / a2d68d3c / 51462fc5 | Slippage param / OOS trade exports / GBPUSD+USDJPY cost runs | parked w/ triggers |
| 047cd91d | Complete in work (verified, lifecycle close blocked by claim-gate bug; see card comment) | — |

## Next milestones
1. 758273a7 harness isolation (before ANY further harness run)
2. 1 week live under D5 → gate-loosening decision (plan §Phase 1.3)
3. Phase 2 tournament scaffold (architecture-lane doc)

*Written by Ava 2026-09-08 12:45 EDT. ~wm~mode:sharp~*

---

## Afternoon addendum (2026-09-08 ~15:45 EDT) — FULL STACK LIVE

**Second Craig-approved restart** (PID 3236819, 19:39 UTC) applied the afternoon stack:
- 3de9203f — per-symbol 3-AT-RISK slot policy (breakeven/in-profit exempt; production ratchet wire-up releases slots live)
- 98f080c6 — sane_max 5000→10000 + loud rejection counter (~25% of signal flow was silently discarded)
- 0d229f0d — KZ leg restored (duplicate MarketState h4_bars; was dead since H4 filter)
- 88f42e94 — SL fills at level + pre-trade FTMO gate
- 342f91db — harness state isolation (post-incident)

Startup verified: broker synced $10,262.45, peak truth-reconciled to current balance, 0 positions, FTMOGuard active kill_switch=wired, D5 envelope live.

**Open Ayumi debt (workboard):** e1e32b07 (worktree PID-guard gap, high) · 171dcc39 (MarketState consolidation) · 644c565b (eval-loop halt) · 46b631ab (slippage param, w/ XAU port) · a2d68d3c (OOS trade exports) · 51462fc5 (GBPUSD/USDJPY cost runs) · d996375c (directional-lock sweep, post Asia-freeze) · 75b24f98+047cd91d (lifecycle closes blocked by claim-gate bug, work verified on disk).
**Next milestone:** 1-week live window → gate-loosening decision (~Sep 15) → Phase 2 tournament scaffold.

*— Ava*
