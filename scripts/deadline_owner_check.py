#!/usr/bin/env python3
"""Deadline owner-tag contract scanner.

Purpose
-------
Sprint / plan / deadline docs are only useful when someone is actually
accountable for each date. This scanner enforces a two-tag contract:

    CRAIG-OWNED  - the date lives on a calendar slot that a named human
                   (currently Craig) must hit. Automation escalates on miss.
    AGENT-OWNED  - the date is enforced by automation; no human action
                   required at the slot boundary.

A date with neither tag is **untagged**. Untagged dates are the failure
mode that produced the Cabal Aug-10 / briefing-pack Aug-11 advisory-deadline
trap. Per card 0b910897, untagged dates must be flagged at plan time and
removed automatically.

Output modes
------------
* Default (no --strip): print a machine-readable JSON report to stdout with
  one entry per untagged date, plus a human-readable summary to stderr.
  Exit code 0 if no untagged dates are found, 1 otherwise.
* --strip: read the file, write the cleaned copy to stdout (or --output),
  and report each removed date to stderr. Original file is left untouched
  unless --in-place is also passed.

Tag markers
-----------
Recognised markers (case-sensitive, must appear in the same logical line as
the date, optionally inside backticks or square brackets):

    CRAIG-OWNED, [CRAIG-OWNED], `CRAIG-OWNED`
    AGENT-OWNED, [AGENT-OWNED], `AGENT-OWNED`

Date patterns recognised
------------------------
* ISO date:           2026-09-07, 2026-09-07T16:00, 2026-09-07T16:00:00Z
* US slash:           09/07/2026 (treated as MM/DD/YYYY — sanity-checked)
* Long-form:          September 7, 2026   /   Sep 7, 2026   /   Sep 7 2026
* Sprint-style:       2026-09-07 (same as ISO; covered above)

Usage
-----
    scripts/deadline_owner_check.py path/to/doc.md
    scripts/deadline_owner_check.py --strip path/to/doc.md > cleaned.md
    scripts/deadline_owner_check.py --in-place --strip path/to/doc.md
    scripts/deadline_owner_check.py --json path/to/doc.md
    scripts/deadline_owner_check.py path/to/doc.md --quiet   # only summary
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Tag and date patterns
# ---------------------------------------------------------------------------

_OWNER_TAGS = ("CRAIG-OWNED", "AGENT-OWNED")
_TAG_PATTERN = re.compile(
    r"(?:`|\[)?\s*(?P<tag>CRAIG-OWNED|AGENT-OWNED)\s*(?:`|\])?",
)

# Order matters: ISO-style first to avoid partial-match swallowing digits.
_DATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "iso",
        re.compile(
            r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})"
            r"(?:[T ](?P<hh>\d{2}):(?P<mm>\d{2})(?::(?P<ss>\d{2}))?"
            r"(?:Z|[+\-]\d{2}:?\d{2})?)?\b"
        ),
    ),
    (
        "us_slash",
        re.compile(r"\b(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{4})\b"),
    ),
    (
        "long_form",
        re.compile(
            r"\b(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|"
            r"Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
            r"\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?"
            r"(?:,\s*|\s+)(?P<y>\d{4})\b"
        ),
    ),
)

_MONTH_LOOKUP: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# Common non-deadline words that look like dates but are actually code/version
# refs (e.g. `python 3.12`, `semver 1.0.0`, `RFC 2026-09-07` inside a URL).
# Treated as date-context suppressors within ±40 chars of the match.
_DATE_FALSE_POSITIVE_HINTS: tuple[str, ...] = (
    "version",
    "v3.",
    "semver",
    "RFC ",
    "issue-",
    "issue/",
    "PR #",
    "PR/",
    "card ",
    "card-",
    "c0",  # card id prefixes
    "doc-",
)

# Lines that are pure headings or table separators get tagged-checked but
# never stripped — even untagged dates here are "documentation about dates"
# rather than deadlines. Detect headings via markdown-ish markers.
_HEADING_PREFIX = re.compile(r"^\s{0,3}#{1,6}\s")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:\-|]+\|?\s*$")


# ---------------------------------------------------------------------------
# Datatypes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DateHit:
    """A single date match with provenance for the report."""

    line_no: int
    col_start: int
    col_end: int
    matched_text: str
    canonical: str  # ISO form (YYYY-MM-DD) when parseable, else raw
    pattern_kind: str
    owner: str | None  # "CRAIG-OWNED" | "AGENT-OWNED" | None
    snippet: str

    def to_json(self) -> dict[str, object]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def _line_has_tag(line: str, span: tuple[int, int]) -> str | None:
    """Return the owner tag found near a date, else None.

    Tags may appear before or after the date on the same logical line.
    We look in a ±64-character window centred on the match. Tags inside
    markdown decorations (backticks, square brackets) are recognised.
    """
    start, end = span
    pad_lo = max(0, start - 64)
    pad_hi = min(len(line), end + 64)
    window = line[pad_lo:pad_hi]
    match = _TAG_PATTERN.search(window)
    return match.group("tag") if match else None


def _looks_like_false_positive(line: str, span: tuple[int, int]) -> bool:
    """Suppress matches that look like version refs, issue IDs, etc."""
    start, end = span
    pad_lo = max(0, start - 40)
    pad_hi = min(len(line), end + 40)
    neighbourhood = line[pad_lo:pad_hi].lower()
    return any(hint.lower() in neighbourhood for hint in _DATE_FALSE_POSITIVE_HINTS)


def _to_iso(kind: str, match: re.Match[str]) -> str | None:
    """Return ISO-form YYYY-MM-DD for the match, or None if invalid."""
    try:
        if kind == "iso":
            return f"{int(match.group('y')):04d}-{int(match.group('m')):02d}-{int(match.group('d')):02d}"
        if kind == "us_slash":
            return _us_slash_to_iso(match)
        if kind == "long_form":
            return _long_form_to_iso(match)
    except (ValueError, IndexError):
        return None
    return None


def _us_slash_to_iso(match: re.Match[str]) -> str | None:
    month = int(match.group("m"))
    day = int(match.group("d"))
    year = int(match.group("y"))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _long_form_to_iso(match: re.Match[str]) -> str | None:
    day = int(match.group("d"))
    year = int(match.group("y"))
    month_word = match.group(0).split()[0].lower()
    month = _MONTH_LOOKUP.get(month_word)
    if month is None:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _is_heading_or_table(line: str) -> bool:
    return bool(_HEADING_PREFIX.match(line) or _TABLE_SEPARATOR.match(line))


def scan_text(text: str) -> list[DateHit]:
    """Scan a document body and return every DateHit found.

    Headings and pure table-separator lines are skipped — those are
    documentation about dates, not deadlines.
    """
    hits: list[DateHit] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if _is_heading_or_table(line):
            continue
        for kind, pattern in _DATE_PATTERNS:
            for match in pattern.finditer(line):
                span = (match.start(), match.end())
                if _looks_like_false_positive(line, span):
                    continue
                iso = _to_iso(kind, match)
                canonical = iso or match.group(0)
                owner = _line_has_tag(line, span)
                snippet = line.strip()[:160]
                hits.append(
                    DateHit(
                        line_no=line_no,
                        col_start=match.start(),
                        col_end=match.end(),
                        matched_text=match.group(0),
                        canonical=canonical,
                        pattern_kind=kind,
                        owner=owner,
                        snippet=snippet,
                    )
                )
    return hits


def partition(hits: Iterable[DateHit]) -> tuple[list[DateHit], list[DateHit]]:
    """Split hits into (untagged, tagged)."""
    untagged: list[DateHit] = []
    tagged: list[DateHit] = []
    for hit in hits:
        (tagged if hit.owner else untagged).append(hit)
    return untagged, tagged


# ---------------------------------------------------------------------------
# Stripping
# ---------------------------------------------------------------------------


def _strip_date_token(line: str, span: tuple[int, int]) -> str:
    """Remove a date token from a line, collapsing extra whitespace."""
    start, end = span
    pre = line[:start].rstrip()
    post = line[end:].lstrip()
    if pre and post:
        return f"{pre} {post}"
    return pre + post


def strip_untagged(text: str, hits: list[DateHit]) -> str:
    """Return `text` with untagged dates removed in-place.

    Tags are preserved; only the date itself is dropped from the line. Each
    removal collapses surrounding whitespace and never joins unrelated
    sections.
    """
    lines = text.splitlines(keepends=True)
    by_line: dict[int, list[DateHit]] = {}
    for hit in hits:
        if hit.owner:
            continue
        by_line.setdefault(hit.line_no, []).append(hit)

    for line_no, line_hits in by_line.items():
        original = lines[line_no - 1]
        # Strip right-to-left so col offsets stay valid.
        for hit in sorted(line_hits, key=lambda h: h.col_start, reverse=True):
            # Re-locate the substring in case earlier strips shifted offsets.
            idx = original.find(hit.matched_text, max(0, hit.col_start - 1))
            if idx < 0:
                continue
            new_end = idx + len(hit.matched_text)
            original = _strip_date_token(original, (idx, new_end))
        lines[line_no - 1] = original
    return "".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_input(path: str | None) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _write_output(text: str, output: str | None, in_place: bool, source: str | None) -> None:
    if in_place and source and source != "-":
        Path(source).write_text(text, encoding="utf-8")
        return
    if output:
        Path(output).write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)


def _emit_report(
    hits: list[DateHit],
    untagged: list[DateHit],
    *,
    as_json: bool,
    quiet: bool,
) -> None:
    summary = {
        "total_dates": len(hits),
        "tagged": len(hits) - len(untagged),
        "untagged": len(untagged),
        "untagged_entries": [h.to_json() for h in untagged],
    }
    if as_json:
        json.dump(summary, sys.stdout, indent=2, sort_keys=False)
        sys.stdout.write("\n")
        return
    if quiet:
        return
    sys.stderr.write(
        f"deadline_owner_check: {summary['total_dates']} date(s) "
        f"({summary['tagged']} tagged, {summary['untagged']} untagged)\n"
    )
    for hit in untagged:
        sys.stderr.write(
            f"  L{hit.line_no}:{hit.col_start}-{hit.col_end}  "
            f"{hit.matched_text}  ({hit.canonical})  "
            f"owner=NONE  | {hit.snippet}\n"
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deadline_owner_check.py",
        description=(
            "Scan a sprint/plan doc for dates missing a CRAIG-OWNED or "
            "AGENT-OWNED tag. Optionally strip untagged dates."
        ),
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="-",
        help="File to scan. '-' or omit to read stdin.",
    )
    parser.add_argument(
        "--strip",
        action="store_true",
        help="Remove untagged dates from the document (writes to stdout).",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="With --strip, overwrite the source file instead of stdout.",
    )
    parser.add_argument(
        "--output",
        help="With --strip, write the cleaned copy to this path.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report on stdout instead of human-readable text.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable summary on stderr.",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "Shadow mode: print a baseline JSON suitable for inclusion in "
            "docs/ops/deadline-contract.md (counts + per-doc distribution)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    text = _read_input(args.path)
    hits = scan_text(text)
    untagged, _tagged = partition(hits)

    if args.baseline:
        # Per-doc baseline: counts only (no per-line detail). Designed to be
        # embedded in markdown so reviewers can see where the backlog lives.
        per_doc = {
            "total_dates": len(hits),
            "tagged": len(hits) - len(untagged),
            "untagged": len(untagged),
        }
        sys.stdout.write(json.dumps(per_doc, indent=2, sort_keys=False) + "\n")
        return 0 if not untagged else 1

    if args.strip:
        cleaned = strip_untagged(text, untagged)
        _write_output(cleaned, args.output, args.in_place, args.path)
        sys.stderr.write(
            f"deadline_owner_check --strip: removed {len(untagged)} untagged date(s) "
            f"from {args.path if args.path != '-' else '<stdin>'}\n"
        )
        for hit in untagged:
            sys.stderr.write(
                f"  removed L{hit.line_no}: {hit.matched_text} ({hit.canonical})\n"
            )
        return 0

    _emit_report(hits, untagged, as_json=args.json, quiet=args.quiet)
    return 1 if untagged else 0


if __name__ == "__main__":
    sys.exit(main())
