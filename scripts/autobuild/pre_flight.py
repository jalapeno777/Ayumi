#!/usr/bin/env python3
"""Autobuild pre-flight checks for Ayumi.

This script is designed to run inside an Ayumi worktree before the builder
creates a commit. It imports the reusable guards from ``scope_guard.py`` and
prints a concise, machine-readable verdict.

Intended invocation from the repo root:

    python3 scripts/autobuild/pre_flight.py scripts/one.py scripts/two.py

The optional positional arguments are the ``allowed_files`` for the current
card. If none are provided the guards that depend on allowed files will report
an empty check set.
"""

from __future__ import annotations

import json
import sys

# Local import: add repo root to sys.path so the package resolves regardless of
# how the script is invoked.
import sys as _sys
from pathlib import Path

_sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.autobuild.scope_guard import (
    ScopeGuardError,
    commit_size,
    function_removals,
    gitignore_modified,
)


def pre_flight(repo: Path, allowed_files: list[str]) -> dict:
    """Run all three guards and assemble a verdict.

    Returns:
        A dictionary with the raw guard results plus ``warnings`` and
        ``blocked`` booleans. ``blocked`` is True when a hard guard fires
        (currently function removals inside allowed files). ``warnings`` is
        True when the commit is oversized or ``.gitignore`` was modified.
    """
    try:
        gitignore_result = gitignore_modified(repo)
        size_result = commit_size(repo)
        removal_result = function_removals(repo, allowed_files)
    except ScopeGuardError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "warnings": True,
            "blocked": True,
        }

    warnings = gitignore_result["modified"] or size_result["warn"]
    blocked = removal_result["flagged"]

    return {
        "ok": not (warnings or blocked),
        "warnings": warnings,
        "blocked": blocked,
        "gitignore": gitignore_result,
        "commit_size": size_result,
        "function_removals": removal_result,
    }


def main() -> int:
    """CLI entry point."""
    repo = Path.cwd()
    allowed_files = sys.argv[1:]
    report = pre_flight(repo, allowed_files)
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
