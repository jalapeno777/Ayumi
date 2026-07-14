# Ayumi Decision Log

Decisions that affect project direction. Newest first.

---

## 2026-07-13

### D-001: FTMO Account Type Locked
- **Decision:** FTMO 1-Step Standard, $10,000 starting balance
- **Rationale:** No minimum trading days, 90% profit split, 3% daily DD, 10% total DD
- **Made by:** Craig

### D-002: Repo Cleanup — Delete Dead Code
- **Decision:** Delete `src/forex_trading/`, `src/crypto/`, `docs/media/`, `_archive/`, deprecated scripts
- **Rationale:** 175 files / 39K lines of dead code causing confusion. Can rebuild from scratch if needed.
- **Commit:** `9fa2fd8`

### D-003: Canonical Roadmap Established
- **Decision:** `docs/roadmaps/ayumi-master-roadmap.md` is the single source of truth. All prior plans superseded.
- **Rationale:** 6+ prior plan docs with conflicting information. Need one canonical reference.
- **Commit:** `fc07433`

### D-004: CDN Download Scripts Deprecated
- **Decision:** `scripts/download_dukascopy.py` and `scripts/download_dukascopy_crisis.py` deleted. All data download via Docker SDK harvester (`tools/dukascopy-harvester/`).
- **Rationale:** CDN script was unreliable. Docker SDK uses official JForex SDK with proper rate limiting.
- **Commit:** `a20baf5`

### D-005: Paper Trading on cTrader Demo
- **Decision:** Phase 3 validation runs on cTrader demo account, not local paper trading.
- **Rationale:** Validates full execution path (signal → confidence → position sizing → cTrader order → TP/SL → risk guard) simultaneously.
- **Added to roadmap:** Phase 3 updated.

### D-006: Docker `--network host` Required
- **Decision:** All Docker harvester runs must use `--network host` flag.
- **Rationale:** Fixes Cloudflare/DNS issue that caused JNLP 404 from inside containers.

### D-007: SRF Infrastructure Fixes
- **Decision:** Restore `strategy_legacy.py`, fix SRF factory call, fix DB schema, gitignore QA output
- **Rationale:** Cleanup commit deleted `strategy_legacy.py` which 5 files import. SRF CLI passed instance instead of callable. DB had NOT NULL columns the insert code didn't populate. QA validator wrote to file that dirtied git tree.
- **Commits:** `51fc2d3`, `f252086`, `24041e4`

### D-008: ttc_xauusd "PF=8 Anomaly" Was Fiction
- **Decision:** No look-ahead bug investigation needed. Actual SRF data shows PF=2.25, WR=47.3%.
- **Rationale:** Research doc `strategy-optimization-research.md` reported PF=8 based on stale or incorrect data. Live DB query confirms PF=2.25. Roadmap task 1A.1 can be skipped.

### D-009: GBPUSD Data Is Current
- **Decision:** GBPUSD data is NOT stale (contrary to initial inventory). Data runs to Jul 2026.
- **Rationale:** DuckDB query confirms 117M ticks with recent timestamps. Roadmap updated.

### D-010: Archive Superseded Docs
- **Decision:** Move all superseded plan/forex/research docs to `docs/_archive/`. Delete obvious junk (copy-trading, TikTok, marketing). Card `7843e2e5` tracks harvesting remaining nuggets.
- **Rationale:** 90+ stale docs causing confusion about what's current. Single source of truth must be obvious.
