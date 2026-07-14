# Council Review: BQ-681 Token TTL Refresh Manager

**Reviewers:** Kaito (Systems), Liora (Learning & Data Quality)
**Plan:** `docs/plans/bq681-token-ttl-refresh.md`
**Date:** 2026-06-12
**SP:** 2

---

## Kaito (Systems)

**Verdict: APPROVE_WITH_CONCERNS**

Kaito's primary concern is that BQ-681 introduces a new standalone component (`TokenManager`) without adequately addressing why the existing inline implementation in `OpenApiSpotFeed` is insufficient. The current system already has programmatic refresh, proactive refresh at 80% TTL, reactive refresh on auth failure, token persistence to `.env`, circuit breaker logic, and expiry tracking. The plan must justify the refactoring overhead more rigorously.

### K-1: Missing Justification for Component Extraction
**Severity: Medium**

The plan lists four gaps but does not quantify their impact. Specifically:
- Gap 1 (No startup validation): The launcher already fails with a clear error if tokens are missing or placeholders (`start()` checks `_PLACEHOLDER_VALUES`). A pre-flight check in `launch_blend_forward_test.py` could be added in ~5 lines without a new module.
- Gap 2 (No token state file): This is the strongest justification. A JSON state file tracking issue time, TTL, and refresh history would indeed aid debugging and observability.
- Gap 3 (No pre-expiry warning): The proactive refresh at 80% TTL is already a warning system. Adding configurable `warn_days_before` is nice-to-have, not critical.
- Gap 4 (No standalone testable component): The existing `_refresh_token_and_reauth()` method is already testable if extracted into a function. A full class may be overkill.

**Amendment K-1:** Add a "Cost-Benefit" section to the plan quantifying time spent debugging token issues in the last 30 days. If the number is low, consider a lighter refactor (extract functions, add state file) rather than a new class.

### K-2: `.env` Write Race Condition Underestimated
**Severity: Medium**

The plan mentions PID guard prevents duplicate forward test instances, but `.env` is also written by `CTraderOpenApiClient` (used in `fetch_bars` and `launch_blend_forward_test.py` for historical data preload). If the spot feed refreshes tokens while the preloader client is active, the preloader may read stale tokens or the spot feed may overwrite tokens the preloader just refreshed.

The `TokenManager` should use atomic writes (`write to temp + rename`) or file locking. The current `_persist_tokens()` does a naive `read_text()`/`write_text()` which is non-atomic.

**Amendment K-2:** Update `TokenManager` design to use atomic file writes for `.env` updates. Document the interaction between `CTraderOpenApiClient` and `OpenApiSpotFeed` token refresh.

### K-3: Startup Validation Integration Point is Fragile
**Severity: Low**

The proposed `validate_on_startup()` returns `ValidationResult` with `placeholder_detected`. However, the launcher also creates a `CTraderOpenApiClient` for bar preloading *before* the engine starts. If `validate_on_startup()` flags a critical token issue, the preloader may have already used the bad token. The validation should happen before any OpenAPI client instantiation.

**Amendment K-3:** Reorder `launch_blend_forward_test.py` so token validation happens before the `CTraderOpenApiClient` is created for bar fetching.

### K-4: Token Refresh Endpoint URL Hardcoded
**Severity: Low**

The refresh URL `https://openapi.ctrader.com/apps/token` is hardcoded in `_refresh_token_and_reauth()`. The plan does not mention making this configurable in `TokenManager`.

**Amendment K-4:** Make the OAuth token endpoint URL a constructor parameter in `TokenManager` with the cTrader URL as default.

---

## Liora (Learning & Data Quality)

**Verdict: APPROVE_WITH_CONCERNS**

Liora's focus is on data quality, observability, and test coverage. She agrees a `TokenManager` is useful for audit trails but is concerned about state file schema evolution and test isolation.

### L-1: Token State Schema Must Be Versioned
**Severity: Medium**

The `TokenState` dataclass includes `refresh_history: list[RefreshRecord]`. If this schema changes in the future (e.g., adding fields), old state files will fail to load or silently drop data. The plan mentions "JSON parse error → rebuild from `.env`" but does not specify a schema version field.

**Amendment L-1:** Add a `schema_version: int` field to `TokenState` (default 1). The `load_state()` method should detect unknown versions and either migrate or gracefully rebuild from `.env`.

### L-2: Refresh History Needs a Cap to Prevent Unbounded Growth
**Severity: Medium**

The `refresh_history` list in `TokenState` grows without bound. Over months of operation, this could result in a multi-megabyte JSON file. The plan does not specify a retention policy.

**Amendment L-2:** Limit `refresh_history` to the last N records (suggest N=50). Document this cap in the plan and add an acceptance criterion for it.

### L-3: Unit Tests Must Cover Edge Cases in Token Refresh Response
**Severity: Medium**

The existing `_refresh_token_and_reauth()` already handles multiple response key variants (`accessToken`/`access_token`, `expiresIn`/`expires_in`). The `TokenManager.refresh()` must preserve this robustness. The test plan should explicitly cover:
- Response with only `access_token` (no `refresh_token`)
- Response with missing `expires_in`
- Response with `errorCode` but no `description`
- HTTP 4xx/5xx responses

**Amendment L-3:** Expand the unit test acceptance criterion to list these specific response edge cases.

### L-4: Startup Validation Should Log Structured Metrics
**Severity: Low**

The plan proposes `validate_on_startup()` but does not specify how validation outcomes are observed. For operational health monitoring, the system should emit structured metrics (e.g., `token_validation_result`, `days_remaining`, `warning_level`).

**Amendment L-4:** Add a requirement for `TokenManager` to log structured metrics on validation and refresh outcomes, suitable for scraping by the health monitoring system.

---

## Synthesis

### Overall Assessment

BQ-681 addresses real operational gaps (startup validation, state tracking, observability) but the proposed solution is heavier than strictly necessary. The existing inline refresh implementation in `OpenApiSpotFeed` is already functional; the primary deficiencies are around state persistence and startup hygiene.

### Recommended Path Forward

**Option A (Recommended): Streamlined Refactor**
1. Extract `_refresh_token_and_reauth()` and `_persist_tokens()` into a standalone `token_manager.py` module, keeping the logic largely intact.
2. Add `TokenState` JSON persistence with schema versioning and capped history.
3. Add `validate_on_startup()` callable from the launcher.
4. Integrate into `OpenApiSpotFeed` as optional delegation (backward compat).
5. Add unit tests for the extracted functions.

**Option B (Plan as Written): Full Class Refactor**
Proceed with the full `TokenManager` class but address amendments K-1 through L-4. This adds ~1-2 hours but provides a cleaner abstraction.

### SP Estimate
- The current SP estimate of **2** is fair for Option A.
- If pursuing Option B with all amendments, consider **2.5 SP** or accept that some acceptance criteria may slip to a follow-up BQ.

### Key Takeaways
1. **Automated refresh is already working** — the plan correctly notes this. The value of BQ-681 is in observability and testability, not enabling new functionality.
2. **The `.env` write race is the biggest operational risk** — atomic writes or explicit documentation of the preloader/spot-feed interaction is needed.
3. **Schema versioning for `TokenState` is non-negotiable** if this component is expected to persist across deployments.
4. **Consider a lighter refactor** if the team is time-constrained; the full class abstraction is elegant but not strictly required.

### Amendments Summary Table

| ID | Reviewer | Severity | Description | SP Impact |
|----|----------|----------|-------------|-----------|
| K-1 | Kaito | Medium | Add cost-benefit justification for new component | None |
| K-2 | Kaito | Medium | Use atomic file writes for `.env` updates | +0.25 |
| K-3 | Kaito | Low | Reorder launcher so validation precedes preloader | None |
| K-4 | Kaito | Low | Make OAuth endpoint URL configurable | None |
| L-1 | Liora | Medium | Add `schema_version` to `TokenState` | +0.25 |
| L-2 | Liora | Medium | Cap `refresh_history` to last N records | None |
| L-3 | Liora | Medium | Expand test coverage for edge cases | +0.25 |
| L-4 | Liora | Low | Log structured metrics from validation/refresh | None |

---

*Council review complete. Both reviewers recommend APPROVE_WITH_CONCERNS and suggest addressing amendments before or during implementation.*
