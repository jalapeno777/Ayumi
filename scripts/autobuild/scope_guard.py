"""Autobuild scope guards for Ayumi.

This module provides lightweight, git-based checks intended to catch the kinds of
scope/behaviour problems that tripped up an earlier autobuild run:

- large commits that pull in unrelated files
- .gitignore changes that can hide untracked data
- function removals inside allowed files (a proxy for behaviour change)

The functions return plain dictionaries so callers can decide whether to warn,
block, or log.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class ScopeGuardError(Exception):
    """Raised when a guard cannot be evaluated (e.g. not inside a git repo)."""


@dataclass(frozen=True)
class DiffStat:
    insertions: int
    deletions: int
    files_changed: int


def _run_git(repo: Path, args: list[str]) -> str:
    """Run a git command inside ``repo`` and return stdout text."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ScopeGuardError(f"git {' '.join(args)} failed in {repo}: {exc.stderr.strip()}") from exc
    except FileNotFoundError as exc:
        raise ScopeGuardError(f"git not found: {exc}") from exc
    return result.stdout


def gitignore_modified(repo: Path, base_ref: str = "origin/main") -> dict:
    """Return whether ``.gitignore`` was modified between ``base_ref`` and HEAD.

    Args:
        repo: Path to the git repository.
        base_ref: Reference to diff against. Defaults to ``origin/main``.

    Returns:
        A dictionary with keys ``modified`` (bool), ``base_ref`` (str),
        and ``diff_files`` (list of file paths reported by git diff).
    """
    stdout = _run_git(repo, ["diff", "--name-only", f"{base_ref}..HEAD"])
    files = [line.strip() for line in stdout.splitlines() if line.strip()]
    modified = ".gitignore" in files
    return {
        "modified": modified,
        "base_ref": base_ref,
        "diff_files": files,
    }


def commit_size(repo: Path, base_ref: str = "origin/main") -> dict:
    """Return insertion/deletion counts and a warning flag for large commits.

    The threshold is fixed at 5,000 insertions as requested by the originating
    debt card. Deletions are reported for completeness but do not trigger the
    warning.

    Args:
        repo: Path to the git repository.
        base_ref: Reference to diff against. Defaults to ``origin/main``.

    Returns:
        A dictionary with keys ``insertions``, ``deletions``, ``files_changed``,
        ``threshold``, and ``warn``.
    """
    stdout = _run_git(
        repo,
        ["diff", "--shortstat", f"{base_ref}..HEAD"],
    )
    stat = _parse_shortstat(stdout)
    threshold = 5000
    return {
        "insertions": stat.insertions,
        "deletions": stat.deletions,
        "files_changed": stat.files_changed,
        "threshold": threshold,
        "warn": stat.insertions > threshold,
    }


def _parse_shortstat(text: str) -> DiffStat:
    """Parse git diff --shortstat output.

    Sample inputs:
        " 3 files changed, 10 insertions(+), 4 deletions(-)"
        " 1 file changed, 2 insertions(+)"
        " 1 file changed, 5 deletions(-)"
        "" (empty)
    """
    text = text.strip()
    if not text:
        return DiffStat(insertions=0, deletions=0, files_changed=0)

    files_match = re.search(r"(\d+) file(?:s)? changed", text)
    insertions_match = re.search(r"(\d+) insertion(?:s)?", text)
    deletions_match = re.search(r"(\d+) deletion(?:s)?", text)

    return DiffStat(
        files_changed=int(files_match.group(1)) if files_match else 0,
        insertions=int(insertions_match.group(1)) if insertions_match else 0,
        deletions=int(deletions_match.group(1)) if deletions_match else 0,
    )


def _function_defs(source: str) -> set[str]:
    """Return the set of top-level function names defined in *source*."""
    pattern = re.compile(r"^def\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)
    return set(pattern.findall(source))


def function_removals(
    repo: Path,
    allowed_files: Iterable[str],
    base_ref: str = "origin/main",
) -> dict:
    """Detect function definitions removed from allowed files.

    This is intentionally a heuristic: it compares top-level ``def`` names in
    the version on ``base_ref`` with the version at HEAD. Any function that
    existed in the base but is missing from HEAD is flagged. The result is a
    mapping from file path to a list of removed function names.

    Args:
        repo: Path to the git repository.
        allowed_files: Files to inspect, relative to the repo root.
        base_ref: Reference to diff against. Defaults to ``origin/main``.

    Returns:
        A dictionary with keys ``flagged`` (bool), ``removals`` (dict), and
        ``checked`` (int, number of files successfully inspected).
    """
    removals: dict[str, list[str]] = {}
    checked = 0

    for rel_path in allowed_files:
        if not rel_path.endswith(".py"):
            continue

        try:
            base_blob = _run_git(repo, ["show", f"{base_ref}:{rel_path}"])
        except ScopeGuardError:
            # File does not exist on base ref; nothing to compare.
            continue

        head_path = repo / rel_path
        try:
            head_blob = head_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # File was deleted outright. Treat every base function as removed.
            head_blob = ""
        except Exception:  # noqa: S112
            # Unreadable for other reasons; skip to keep the guard heuristic.
            continue

        checked += 1
        base_funcs = _function_defs(base_blob)
        head_funcs = _function_defs(head_blob)
        removed = sorted(base_funcs - head_funcs)
        if removed:
            removals[rel_path] = removed

    return {
        "flagged": bool(removals),
        "removals": removals,
        "checked": checked,
    }


def run_all(
    repo: Path,
    allowed_files: Iterable[str] | None = None,
    base_ref: str = "origin/main",
) -> dict:
    """Run all three scope guards and return a combined report."""
    allowed_files = list(allowed_files or [])
    return {
        "gitignore": gitignore_modified(repo, base_ref),
        "commit_size": commit_size(repo, base_ref),
        "function_removals": function_removals(repo, allowed_files, base_ref),
    }


def main() -> None:
    """CLI entry point: print a JSON report for the current repo."""
    import json
    import sys

    repo = Path.cwd()
    allowed_files = sys.argv[1:] or []
    report = run_all(repo, allowed_files)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
