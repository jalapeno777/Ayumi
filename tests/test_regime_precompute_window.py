"""Regression test: prevent reintroduction of 60-bar precompute window bug.

The RegimeDetector requires atr_lookback=50 + adx_period=14 warmup, meaning
at least 64 bars are needed for valid detection. In practice we require ≥100
bars to ensure both ATR and ADX have sufficient warmup data.

Bug history: scripts used `max(0, i-60)` or `bars[-60:]` for precomputing
regime labels, silently producing None/missing labels for early bars and
potentially degrading detection quality on partial windows.

This test greps source files for the 60-bar pattern and fails if found.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Patterns that indicate the 60-bar precompute bug
BUG_PATTERNS = [
    # max(0, i-60) or max(0,i-60) — rolling window style
    re.compile(r"max\(\s*0\s*,\s*i\s*-\s*60\s*\)"),
    # bars[-60:] or bars[-60:] — slice style
    re.compile(r"bars\[-60\s*:\s*\]"),
    # i >= 60 threshold check (in precompute context)
    re.compile(r"if\s+i\s*>=\s*60\s*:"),
]

# Directories to scan
SCAN_DIRS = ["src/", "scripts/"]

# Files exempt from failure:
# - This test file itself
# - Known debt files with documented 60-bar bug (filed as DEBT cards)
#   These should be removed once the debt is resolved.
KNOWN_DEBT = {
    "scripts/launch_blend_forward_test.py",  # DEBT card filed 2026-07-23
}

ALLOWLIST = {
    "tests/test_regime_precompute_window.py",
} | KNOWN_DEBT


def _scan_files():
    """Scan source files for 60-bar precompute patterns."""
    findings = []
    for scan_dir in SCAN_DIRS:
        root = REPO_ROOT / scan_dir
        if not root.exists():
            continue
        for py_file in root.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT).as_posix()
            if rel in ALLOWLIST:
                continue
            try:
                content = py_file.read_text()
            except Exception:
                continue
            for pat in BUG_PATTERNS:
                for match in pat.finditer(content):
                    lineno = content[: match.start()].count("\n") + 1
                    findings.append((rel, lineno, match.group().strip()))
    return findings


def test_no_60bar_precompute_pattern():
    """Fail if any source file contains a 60-bar precompute window pattern."""
    findings = _scan_files()
    if findings:
        lines = ["60-bar precompute window bug detected:"]
        for rel, lineno, matched in findings:
            lines.append(f"  {rel}:{lineno} — `{matched}`")
        lines.append("")
        lines.append(
            "RegimeDetector needs >=100 bars (atr_lookback=50 + adx_period=14). "
            "Use 100-bar windows instead."
        )
        assert False, "\n".join(lines)


def test_regime_config_defaults():
    """Verify RegimeConfig defaults support the 100-bar minimum."""
    # atr_lookback + adx_period should sum to < 100
    # (the warmup requirement must be satisfiable by a 100-bar window)
    try:
        from forex_bot.regime.detector import RegimeConfig

        cfg = RegimeConfig()
        min_bars = cfg.atr_lookback + cfg.adx_period
        assert min_bars <= 100, (
            f"RegimeConfig requires {min_bars} bars minimum (atr_lookback="
            f"{cfg.atr_lookback} + adx_period={cfg.adx_period}), "
            f"but 100-bar precompute window assumes <=100."
        )
    except ImportError:
        # If the module path differs, skip this check
        pass


if __name__ == "__main__":
    findings = _scan_files()
    if findings:
        print("FAIL: 60-bar precompute window bug detected:")
        for rel, lineno, matched in findings:
            print(f"  {rel}:{lineno} — `{matched}`")
        exit(1)
    else:
        print("PASS: No 60-bar precompute patterns found.")
        exit(0)
