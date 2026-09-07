"""Regression tests for scripts/deadline_owner_check.py.

These tests cover the strip-untagged path that produced the 2026-09-07 Rin
REWORK verdict: _strip_date_token was concatenating lines when a date was
at end-of-line (lstrip() consumed the trailing newline), producing output
like ``**Effective:****Owner:** test`` instead of preserving the line
break. Two report cases — inline markdown bold fields and ``mtime X``
sentences — are pinned here so future refactors cannot regress the
document-structure contract.

Other behaviour (tag detection, --json, --baseline, headings skip) is
covered by the existing fixture pair (sprint-with-untagged-date.md /
sprint-with-tags.md) and the validate_sprint_plan.sh phase3 gate; this
file focuses on the strip-path rules:

    - Date with content on both sides        → keep one space separator
    - Date at end-of-line (content left only) → preserve the newline
    - Date at start-of-line (content right only) → drop leading whitespace
    - Date alone on its line                  → empty line (newline kept)
    - Date with only horizontal whitespace around → empty line (newline kept)
    - Multiple dates on the same line strip right-to-left, never joining tokens
    - Tagged dates are never stripped
    - Every removed date is reported on stderr in deterministic order
"""

from __future__ import annotations

import pytest

# The script lives next to scripts/deadline_owner_check.py; pytest.ini puts
# scripts/ on sys.path so the import resolves under the worktree and the
# main repo alike.
from deadline_owner_check import (  # type: ignore[import-not-found]
    _strip_date_token,
    partition,
    scan_text,
    strip_untagged,
)

# ---------------------------------------------------------------------------
# Direct _strip_date_token tests — pin the per-token rules
# ---------------------------------------------------------------------------


class TestStripDateToken:
    """Pin the per-token strip rules used by --strip / --in-place."""

    def test_inline_bold_field_effective_owner_preserves_newline(self) -> None:
        """The Rin-flagged case: **Effective:** 2026-09-07 must not concatenate
        with the next line. The newline is preserved as a line break."""
        line = "**Effective:** 2026-09-07\n"
        out = _strip_date_token(line, (15, 25))  # '2026-09-07' at col 15..25
        assert out == "**Effective:**\n", (
            f"expected newline preserved; got {out!r}. The original bug "
            "concatenated **Effective:** with the next line's content."
        )

    def test_mtime_sentence_keeps_space_separator(self) -> None:
        """The other Rin-flagged case: 'mtime 2026-07-10 12:13 UTC' must keep
        one space between 'mtime' and 'UTC' so the tokens do not merge."""
        line = "mtime 2026-07-10 12:13 UTC\n"
        # match spans '2026-07-10 12:13' which begins at col 6 and ends at col 22
        out = _strip_date_token(line, (6, 22))
        assert out == "mtime UTC\n", (
            f"expected 'mtime UTC\\n'; got {out!r}. The original bug "
            "produced 'mtime UTC' without preserving the trailing newline, "
            "which is fine, but it also collapsed the separator space."
        )

    def test_content_both_sides_keeps_single_space(self) -> None:
        line = "foo 2026-09-07 bar\n"
        out = _strip_date_token(line, (4, 14))
        assert out == "foo bar\n"

    def test_date_at_start_of_line_drops_leading_padding(self) -> None:
        line = "   2026-09-07 is the deadline\n"
        # '2026-09-07' starts at col 3 and ends at col 13
        out = _strip_date_token(line, (3, 13))
        assert out == "is the deadline\n"

    def test_date_alone_on_line_keeps_line_break(self) -> None:
        line = "2026-09-07\n"
        out = _strip_date_token(line, (0, 10))
        assert out == "\n", "date-alone line should reduce to a blank line"

    def test_date_alone_no_newline_returns_empty(self) -> None:
        line = "2026-09-07"
        out = _strip_date_token(line, (0, 10))
        assert out == ""

    def test_label_then_date_then_nothing(self) -> None:
        line = "Deadline: 2026-09-07\n"
        # '2026-09-07' at col 10..20
        out = _strip_date_token(line, (10, 20))
        assert out == "Deadline:\n", (
            "date at end-of-line after a label: label kept, date + trailing "
            "space dropped, newline preserved"
        )

    def test_horizontal_padding_around_date_collapsed(self) -> None:
        line = "label    2026-09-07    rest\n"
        # date at col 9..19
        out = _strip_date_token(line, (9, 19))
        assert out == "label rest\n", (
            f"expected 'label rest\\n'; got {out!r}. Padding around the "
            "date should be collapsed so tokens do not concatenate."
        )

    def test_iso_with_time_component(self) -> None:
        line = "ts 2026-09-07T16:00:00Z is set\n"
        # match: 2026-09-07T16:00:00Z, col 3..23
        out = _strip_date_token(line, (3, 23))
        assert out == "ts is set\n"

    def test_long_form_date(self) -> None:
        line = "Signed on September 7, 2026 by Craig\n"
        # 'September 7, 2026' begins at col 10 and ends at col 27
        out = _strip_date_token(line, (10, 27))
        assert out == "Signed on by Craig\n"


# ---------------------------------------------------------------------------
# strip_untagged tests — pin end-to-end document-structure behaviour
# ---------------------------------------------------------------------------


class TestStripUntaggedDocumentStructure:
    """Pin behaviour at the document level, including the two Rin cases."""

    def test_rin_case_1_inline_bold_field_preserves_newline(self) -> None:
        """Pin the per-token behaviour that produced the Rin REWORK finding:
        a date at the end of a bold-metadata line must NOT concatenate with
        the next line. Note: this test uses a plain (non-bold) label so
        the scanner actually reports the date — bold-metadata lines are
        suppressed at the scan layer (see TestFrontmatterAwareScan).
        """
        text = (
            "# Test\n"
            "\n"
            "Effective: 2026-09-07\n"
            "Owner: test\n"
        )
        hits = partition(scan_text(text))[0]
        assert len(hits) == 1, (
            f"expected exactly one untagged hit; got {len(hits)}: "
            f"{[(h.line_no, h.matched_text) for h in hits]}"
        )
        cleaned = strip_untagged(text, hits)
        lines = cleaned.splitlines(keepends=True)
        assert lines[2] == "Effective:\n", (
            f"L3 lost its newline; got {lines[2]!r}. Original bug: "
            "strip_untagged concatenated L3 and L4 into "
            "'Effective:Owner: test'."
        )
        assert lines[3] == "Owner: test\n", (
            f"L4 should be untouched; got {lines[3]!r}"
        )

    def test_rin_case_1_bold_metadata_is_suppressed_at_scan(self) -> None:
        """The contract-doc frontmatter uses bold-metadata lines like
        ``**Effective:** 2026-09-07``. These describe the doc itself, not
        deadlines, so the scanner suppresses them at scan time (no untagged
        hits reported). The strip is never invoked on them.
        """
        text = (
            "# Deadline Owner-Tag Contract\n"
            "\n"
            "**Card:** 0b910897-2e60-4556-83d5-e5abd051e505\n"
            "**Effective:** 2026-09-07\n"
            "**Owner of contract:** build lane (Tsubaki)\n"
            "**Approver:** Rin (review)\n"
        )
        hits = scan_text(text)
        assert hits == [], (
            f"bold-metadata header lines must be suppressed at scan; got "
            f"{[(h.line_no, h.matched_text) for h in hits]}"
        )

    def test_rin_case_2_mtime_is_suppressed_at_scan(self) -> None:
        """'mtime 2026-07-10 12:13 UTC' is a snapshot-timestamp citation,
        not a deadline. The scanner suppresses it at scan time so the
        strip is never invoked on it (the doc passes phase3 with no
        untagged dates reported)."""
        text = "evidence: mtime 2026-07-10 12:13 UTC for sprint-008\n"
        hits = scan_text(text)
        assert hits == [], (
            f"'mtime YYYY-MM-DD HH:MM UTC' must be suppressed as non-"
            f"deadline metadata; got {[(h.line_no, h.matched_text) for h in hits]}"
        )

    def test_rin_case_2_strip_keeps_space_separator_when_both_sides_have_content(
        self,
    ) -> None:
        """Sibling of the Rin case: a date between two words. The strip
        keeps exactly one space separator so the surviving tokens do not
        concatenate. (Rin case 2 was originally about 'mtime X UTC', but
        'mtime' is now suppressed at scan — the bug-class is exercised
        here with a non-suppressed prefix.)"""
        text = "sprint 2026-01-02 14:30 UTC opened for review\n"
        hits = partition(scan_text(text))[0]
        assert len(hits) == 1
        cleaned = strip_untagged(text, hits)
        assert cleaned == "sprint UTC opened for review\n", (
            f"expected single-space separator; got {cleaned!r}. Original "
            "bug stripped the date and left 'sprintUTC' (no separator)."
        )

    def test_multiple_dates_on_same_line_strip_right_to_left(self) -> None:
        """Two untagged dates on one line — strip must remove both without
        merging adjacent text."""
        text = "Audit from 2026-07-10 to 2026-07-12 inclusive\n"
        hits = partition(scan_text(text))[0]
        assert len(hits) == 2
        cleaned = strip_untagged(text, hits)
        assert cleaned == "Audit from to inclusive\n"

    def test_tagged_dates_are_preserved(self) -> None:
        """Tagged dates must never be stripped, even when neighbouring an
        untagged date."""
        text = (
            "Deadline: [CRAIG-OWNED] 2026-09-15 — keep\n"
            "Old ref: 2026-07-10 — remove\n"
        )
        hits = partition(scan_text(text))[0]
        cleaned = strip_untagged(text, hits)
        assert "[CRAIG-OWNED] 2026-09-15" in cleaned
        assert "2026-07-10" not in cleaned

    def test_date_alone_on_line_keeps_blank_line(self) -> None:
        text = (
            "heading line\n"
            "2026-09-07\n"
            "trailing line\n"
        )
        hits = partition(scan_text(text))[0]
        cleaned = strip_untagged(text, hits)
        # The date-only line becomes a blank line — surrounding lines
        # must remain separate, not joined into "heading linetrailing line".
        assert cleaned == "heading line\n\ntrailing line\n"

    def test_headings_are_not_scanned_or_stripped(self) -> None:
        text = "# Plan heading 2026-09-07 — title only\nbody 2026-08-01\n"
        hits = partition(scan_text(text))[0]
        cleaned = strip_untagged(text, hits)
        # The heading is untouched; the body date is removed.
        assert cleaned == "# Plan heading 2026-09-07 — title only\nbody\n"


# ---------------------------------------------------------------------------
# strip_untagged stderr reporting — pin the audit trail
# ---------------------------------------------------------------------------


class TestStripUntaggedStderr:
    """Verify the audit trail stays useful for review."""

    def test_every_removed_date_listed_in_deterministic_order(
        self, tmp_path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Use the public CLI so we exercise the full stderr path.
        from deadline_owner_check import main  # type: ignore[import-not-found]

        doc = tmp_path / "doc.md"
        doc.write_text(
            "alpha 2026-01-02 line-a\n"
            "beta  2026-03-04 line-b\n"
            "gamma 2026-05-06 line-c\n",
            encoding="utf-8",
        )
        rc = main(["--strip", "--quiet", str(doc)])
        assert rc == 0
        captured = capsys.readouterr()
        # Header line and three 'removed L<n>:' lines, in input order
        assert "removed 3 untagged date(s)" in captured.err
        assert "2026-01-02" in captured.err
        assert "2026-03-04" in captured.err
        assert "2026-05-06" in captured.err
        # Header must come before the per-line removals
        header_idx = captured.err.index("removed 3")
        first_removal_idx = captured.err.index("removed L1:")
        assert header_idx < first_removal_idx

    def test_tagged_dates_not_listed_as_removed(self, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
        from deadline_owner_check import main  # type: ignore[import-not-found]

        doc = tmp_path / "doc.md"
        doc.write_text("Keep [CRAIG-OWNED] 2026-09-15\n", encoding="utf-8")
        rc = main(["--strip", "--quiet", str(doc)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "removed 0 untagged date(s)" in captured.err
        assert "2026-09-15" not in captured.err


# ---------------------------------------------------------------------------
# mtime false-positive hint — supports the contract-doc self-reference
# ---------------------------------------------------------------------------


class TestMtimeFalsePositive:
    """The contract doc's own example uses 'mtime 2026-07-10 12:13 UTC' as a
    non-deadline metadata pattern. The scanner must treat it as suppressable
    so the shipped contract does not violate its own baseline."""

    def test_mtime_pattern_is_suppressed(self) -> None:
        text = "see mtime 2026-07-10 12:13 UTC for the snapshot\n"
        hits = scan_text(text)
        assert hits == [], (
            f"expected 'mtime YYYY-MM-DD HH:MM UTC' to be suppressed as a "
            f"non-deadline metadata pattern; got {hits!r}"
        )

    def test_effective_metadata_line_suppressed(self) -> None:
        """The contract-doc frontmatter style '**Effective:** YYYY-MM-DD' is
        metadata about the contract itself, not a deadline. We suppress it
        via the frontmatter window so the shipped contract stays clean."""
        text = (
            "# Deadline Owner-Tag Contract\n"
            "\n"
            "**Card:** 0b910897-2e60-4556-83d5-e5abd051e505\n"
            "**Effective:** 2026-09-07\n"
            "**Owner of contract:** build lane (Tsubaki)\n"
            "**Approver:** Rin (review)\n"
            "\n"
            "## Why this exists\n"
            "\n"
            "Real deadline: 2026-09-15\n"
        )
        hits = scan_text(text)
        # The metadata lines (between H1 and H2) are not flagged; only the
        # body deadline is.
        untagged = partition(hits)[0]
        assert len(untagged) == 1, (
            f"expected 1 untagged hit (body deadline); got {len(untagged)}: "
            f"{[(h.line_no, h.matched_text) for h in untagged]}"
        )
        assert untagged[0].matched_text == "2026-09-15"


# ---------------------------------------------------------------------------
# Frontmatter-aware scan: pre-heading metadata is metadata, not a deadline
# ---------------------------------------------------------------------------


class TestFrontmatterAwareScan:
    """Pin the scanner's treatment of frontmatter / metadata headers."""

    def test_yaml_frontmatter_block_is_skipped(self) -> None:
        text = (
            "---\n"
            "card: 0b910897\n"
            "effective: 2026-09-07\n"
            "owner: build lane\n"
            "---\n"
            "\n"
            "# Title\n"
            "\n"
            "Real deadline 2026-09-15 here\n"
        )
        hits = scan_text(text)
        assert len(hits) == 1
        assert hits[0].matched_text == "2026-09-15"
        assert hits[0].line_no == 9

    def test_pre_heading_bold_metadata_is_skipped(self) -> None:
        """Bold-metadata blocks above the first H1 (or above the first H2
        when the doc starts with one) are treated as frontmatter."""
        text = (
            "**Effective:** 2026-09-07\n"
            "**Owner:** build lane\n"
            "\n"
            "# Body heading\n"
            "\n"
            "Body date 2026-09-15 here\n"
        )
        hits = scan_text(text)
        assert len(hits) == 1
        assert hits[0].matched_text == "2026-09-15"

    def test_no_frontmatter_no_skipping(self) -> None:
        """When the doc starts directly with a heading, no skipping happens
        and untagged body dates are still reported."""
        text = (
            "# Heading\n"
            "\n"
            "Body date 2026-09-15 here\n"
        )
        hits = scan_text(text)
        assert len(hits) == 1
        assert hits[0].matched_text == "2026-09-15"
