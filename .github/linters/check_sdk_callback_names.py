#!/usr/bin/env python3
"""SDK callback name linter.

Detects common callback-name typos in cTrader OpenAPI SDK usage:

    setConnectCallback     → should be setConnectedCallback
    setDisconnectCallback  → should be setDisconnectedCallback

Uses Python's ``ast`` module to walk source files — no external deps.

Usage:
    python3 .github/linters/check_sdk_callback_names.py [src_dir]

    Default src_dir: src/

Exit codes:
    0 — No callback typos found
    1 — One or more callback typos detected
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Known typos → correct names
CALLBACK_TYPOS: dict[str, str] = {
    "setConnectCallback": "setConnectedCallback",
    "setDisconnectCallback": "setDisconnectedCallback",
}


def find_callback_typos(source: str, filename: str = "<string>") -> list[dict]:
    """Walk Python source AST and find callback method-call typos.

    Parameters
    ----------
    source : str
        Python source code to lint.
    filename : str
        Filename for reporting (does not affect parsing).

    Returns
    -------
    list of dict
        Each dict has: ``file``, ``line``, ``col``, ``typo``, ``suggestion``.
    """
    violations: list[dict] = []

    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Match pattern: <expr>.setConnectCallback(...)
            if isinstance(func, ast.Attribute) and func.attr in CALLBACK_TYPOS:
                violations.append(
                    {
                        "file": filename,
                        "line": node.lineno,
                        "col": node.col_offset,
                        "typo": func.attr,
                        "suggestion": CALLBACK_TYPOS[func.attr],
                    }
                )

    return violations


def lint_directory(src_dir: str | Path) -> list[dict]:
    """Lint all Python files in a directory tree.

    Returns
    -------
    list of dict
        All violations found across all .py files.
    """
    src_path = Path(src_dir)
    violations: list[dict] = []

    for py_file in sorted(src_path.rglob("*.py")):
        try:
            source = py_file.read_text()
            violations.extend(find_callback_typos(source, str(py_file)))
        except Exception as exc:
            print(f"Warning: could not read {py_file}: {exc}", file=sys.stderr)

    return violations


def main() -> int:
    src_dir = sys.argv[1] if len(sys.argv) > 1 else "src"

    src_path = Path(src_dir)
    if not src_path.exists():
        print(f"Error: directory '{src_dir}' does not exist", file=sys.stderr)
        return 1

    violations = lint_directory(src_path)

    if not violations:
        print("OK: No SDK callback name typos found.")
        return 0

    print(f"Found {len(violations)} callback name typo(s):")
    for v in violations:
        print(f"  {v['file']}:{v['line']}:{v['col']} — '{v['typo']}' should be '{v['suggestion']}'")
    return 1


if __name__ == "__main__":
    sys.exit(main())
