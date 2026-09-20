"""Tests for reviewers.verdicts module.

Every case here is written against the verdict contract in
templates/_shared/verdict_block.partial.md. The parser reads that block
literally; the two failure modes this file exists to hold shut are:

  - a reviewer that says nothing being read as a PASS, and
  - severity being inferred from prose, in either direction.

Before #28 both happened: "nothing critical here" parsed as BLOCK because the
word "critical" was in the Bad section, and "this deletes the ledger on restart"
parsed as WARN because it avoided every keyword in the table.
"""

import inspect

import pytest

import reviewers.verdicts as verdicts_module
from reviewers.verdicts import Finding, ParsedVerdict, VerdictParseError, VerdictParser

INVARIANTS = ["auth_required", "soft_delete_filter", "data_validation"]


def verdict_block(
    verdict: str, blocking: list[str] | None = None, warnings: list[str] | None = None
) -> str:
    """Build a well-formed verdict block for use inside a test response."""
    lines = ["## Verdict", f"VERDICT: {verdict}", "BLOCKING:"]
    lines.extend(f"- {item}" for item in blocking or [])
    lines.append("WARNINGS:")
    lines.extend(f"- {item}" for item in warnings or [])
    return "\n".join(lines)


class TestVerdictParser:
    """Test VerdictParser class."""

    def test_init_with_invariants(self) -> None:
        """Test parser initialization with project invariants."""
        invariants = ["auth_required", "soft_delete_filter", "rate_limit"]
        parser = VerdictParser(invariants)
        assert parser.project_invariants == set(invariants)

    def test_init_empty_invariants(self) -> None:
        """Test parser initialization with empty invariants list."""
        parser = VerdictParser([])
        assert parser.project_invariants == set()


@pytest.fixture
def parser() -> VerdictParser:
    """Create parser with test invariants."""
    return VerdictParser(list(INVARIANTS))


class TestParseVerdict:
    """The happy paths: a well-formed block parses to what it says."""

    def test_parse_verdict_good_bad_ugly_structure(self, parser: VerdictParser) -> None:
        """Prose sections are still captured alongside the declared verdict."""
        raw_response = f"""
## Good
- Code follows established patterns
- Tests are included
- Documentation is comprehensive

## Bad
- Minor style inconsistencies in function names
- Missing type hints in helper functions

## Ugly
- No major architectural concerns

## Closing Question
Have you considered the performance implications of this change?

{verdict_block("WARN", warnings=["Missing type hints in helper functions"])}
"""
        result = parser.parse_verdict(raw_response, "engineer")

        assert result.reviewer == "engineer"
        assert (
            result.good
            == "- Code follows established patterns\n- Tests are included\n- Documentation is comprehensive"
        )
        assert (
            result.bad
            == "- Minor style inconsistencies in function names\n- Missing type hints in helper functions"
        )
        assert result.ugly == "- No major architectural concerns"
        assert (
            result.closing_question
            == "Have you considered the performance implications of this change?"
        )
        assert result.severity == "WARN"
        assert [f.text for f in result.findings] == ["Missing type hints in helper functions"]

    def test_parse_verdict_pass_with_empty_lists(self, parser: VerdictParser) -> None:
        """PASS with both lists empty is the only legal PASS."""
        result = parser.parse_verdict(verdict_block("PASS"), "architect")
        assert result.severity == "PASS"
        assert result.findings == []

    def test_parse_verdict_pass_with_labels_omitted(self, parser: VerdictParser) -> None:
        """A PASS may leave the two labels out entirely."""
        result = parser.parse_verdict("## Verdict\nVERDICT: PASS\n", "sre")
        assert result.severity == "PASS"
        assert result.findings == []

    def test_parse_verdict_block_with_invariant_citation(self, parser: VerdictParser) -> None:
        """A cited BLOCK parses, and the invariant id lands on the finding."""
        raw = verdict_block(
            "BLOCK",
            blocking=["Auth bypass on the login route (invariant: auth_required)"],
            warnings=["Helper lacks a docstring"],
        )
        result = parser.parse_verdict(raw, "sre")

        assert result.severity == "BLOCK"
        assert len(result.findings) == 2

        blocking = [f for f in result.findings if f.severity == "BLOCK"]
        assert len(blocking) == 1
        assert blocking[0].bucket == "bad"
        assert blocking[0].invariant_id == "auth_required"

        warning = next(f for f in result.findings if f.severity == "WARN")
        assert warning.bucket == "ugly"
        assert warning.invariant_id is None

    def test_parse_verdict_block_with_spec_citation(self, parser: VerdictParser) -> None:
        """`spec:` is a citation form; it has no id list to validate against."""
        raw = verdict_block("BLOCK", blocking=["Response omits the cursor field (spec: §4.2)"])
        result = parser.parse_verdict(raw, "architect")
        assert result.severity == "BLOCK"
        assert result.findings[0].invariant_id is None

    def test_parse_verdict_block_with_scope_citation(self, parser: VerdictParser) -> None:
        """`scope:` cites a named section of the dispatched issue."""
        raw = verdict_block(
            "BLOCK", blocking=["Touches renderer/lockfile.py (scope: FILES TO MODIFY)"]
        )
        result = parser.parse_verdict(raw, "engineer")
        assert result.severity == "BLOCK"

    def test_parse_verdict_multiline_finding_joined(self, parser: VerdictParser) -> None:
        """A finding wrapped across lines is one finding."""
        raw = """## Verdict
VERDICT: WARN
BLOCKING:
WARNINGS:
- A long finding that wraps
  across two lines
- A short one
"""
        result = parser.parse_verdict(raw, "engineer")
        assert [f.text for f in result.findings] == [
            "A long finding that wraps across two lines",
            "A short one",
        ]

    def test_parse_verdict_citation_case_insensitive(self, parser: VerdictParser) -> None:
        """Citation keys are matched case-insensitively."""
        raw = verdict_block("BLOCK", blocking=["Issue found (INVARIANT: auth_required)"])
        result = parser.parse_verdict(raw, "engineer")
        assert result.findings[0].invariant_id == "auth_required"

    def test_parse_verdict_last_verdict_line_wins(self, parser: VerdictParser) -> None:
        """A quoted contract above the real block does not decide the verdict."""
        raw = """Here is the format I was given:

VERDICT: PASS | WARN | BLOCK

And here is my review.

## Verdict
VERDICT: PASS
"""
        result = parser.parse_verdict(raw, "engineer")
        assert result.severity == "PASS"

    def test_parse_verdict_placeholder_bullets_are_not_findings(
        self, parser: VerdictParser
    ) -> None:
        """Echoing the template's `<one finding per line>` is not a finding."""
        raw = """## Verdict
VERDICT: PASS
BLOCKING:
- <one finding per line> (invariant: <id> | spec: <section> | scope: <issue section>)
WARNINGS:
- <one finding per line>
"""
        result = parser.parse_verdict(raw, "engineer")
        assert result.severity == "PASS"
        assert result.findings == []


class TestVerdictContractViolations:
    """The contract's four parse errors. Each one is a failed review, not a PASS."""

    def test_missing_verdict_line_is_parse_error(self, parser: VerdictParser) -> None:
        """A review with no VERDICT line cannot be read as anything."""
        raw = """
## Good
- Everything looks fine to me

## Bad
- Nothing critical here

## Ugly
- Nothing
"""
        with pytest.raises(VerdictParseError, match="no VERDICT: line"):
            parser.parse_verdict(raw, "engineer")

    def test_unstructured_response_is_parse_error(self, parser: VerdictParser) -> None:
        """Free prose is a parse error; before #28 it parsed as PASS."""
        with pytest.raises(VerdictParseError, match="no VERDICT: line"):
            parser.parse_verdict("This is not a structured response", "engineer")

    def test_echoed_literal_verdict_is_parse_error(self, parser: VerdictParser) -> None:
        """Leaving `PASS | WARN | BLOCK` in place is a failure, not a PASS."""
        raw = "## Verdict\nVERDICT: PASS | WARN | BLOCK\nBLOCKING:\nWARNINGS:\n"
        with pytest.raises(VerdictParseError, match="must be exactly one of"):
            parser.parse_verdict(raw, "engineer")

    def test_unknown_verdict_word_is_parse_error(self, parser: VerdictParser) -> None:
        """Only the three legal words are accepted."""
        raw = "## Verdict\nVERDICT: APPROVE\n"
        with pytest.raises(VerdictParseError, match="must be exactly one of"):
            parser.parse_verdict(raw, "engineer")

    def test_block_without_citation_is_parse_error(self, parser: VerdictParser) -> None:
        """BLOCK on an uncited finding is taste, and taste does not block."""
        raw = verdict_block("BLOCK", blocking=["I would not have written it this way"])
        with pytest.raises(VerdictParseError, match="no citable BLOCKING finding"):
            parser.parse_verdict(raw, "architect")

    def test_block_with_empty_blocking_list_is_parse_error(self, parser: VerdictParser) -> None:
        """BLOCK must name what it blocks on."""
        raw = verdict_block("BLOCK", warnings=["Only a warning here"])
        with pytest.raises(VerdictParseError, match="empty BLOCKING list"):
            parser.parse_verdict(raw, "sre")

    def test_block_citing_unknown_invariant_is_parse_error(self, parser: VerdictParser) -> None:
        """A fabricated invariant id is exactly what the citation rule prevents."""
        raw = verdict_block("BLOCK", blocking=["Security issue (invariant: nonexistent_rule)"])
        with pytest.raises(VerdictParseError, match="nonexistent_rule"):
            parser.parse_verdict(raw, "architect")

    def test_warning_citing_unknown_invariant_is_parse_error(self, parser: VerdictParser) -> None:
        """The id list is validated wherever it is cited, not only under BLOCK."""
        raw = verdict_block("WARN", warnings=["Minor thing (invariant: made_up_id)"])
        with pytest.raises(VerdictParseError, match="made_up_id"):
            parser.parse_verdict(raw, "engineer")

    def test_warn_without_warnings_is_parse_error(self, parser: VerdictParser) -> None:
        """WARN must name what it warns about."""
        with pytest.raises(VerdictParseError, match="empty WARNINGS list"):
            parser.parse_verdict(verdict_block("WARN"), "engineer")

    def test_pass_with_findings_is_parse_error(self, parser: VerdictParser) -> None:
        """PASS requires both lists empty."""
        raw = verdict_block("PASS", warnings=["Actually there is a problem"])
        with pytest.raises(VerdictParseError, match="PASS with"):
            parser.parse_verdict(raw, "engineer")

    def test_pass_with_the_word_none_as_a_bullet_is_parse_error(
        self, parser: VerdictParser
    ) -> None:
        """The template says so: "none" is a bullet, and a bullet is a finding."""
        raw = verdict_block("PASS", warnings=["none"])
        with pytest.raises(VerdictParseError, match="PASS with"):
            parser.parse_verdict(raw, "engineer")

    def test_empty_citation_value_does_not_count_as_a_citation(self, parser: VerdictParser) -> None:
        """`(invariant: )` is not a citation, so it cannot license a BLOCK."""
        raw = verdict_block("BLOCK", blocking=["Something is wrong (invariant: )"])
        with pytest.raises(VerdictParseError, match="no citable BLOCKING finding"):
            parser.parse_verdict(raw, "engineer")

    def test_unexpected_error_is_wrapped_as_a_parse_error(
        self, parser: VerdictParser, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any failure in here reaches the caller as a parse error, never a PASS."""

        def boom(*_args: object, **_kwargs: object) -> str:
            raise RuntimeError("regex engine exploded")

        monkeypatch.setattr(parser, "_extract_section", boom)
        with pytest.raises(VerdictParseError, match="Failed to parse verdict for engineer"):
            parser.parse_verdict(verdict_block("PASS"), "engineer")


class TestSeverityIsDeclaredNotInferred:
    """The two directions the old keyword table got wrong, held shut."""

    def test_critical_in_prose_does_not_block(self, parser: VerdictParser) -> None:
        """A Bad section reading "nothing critical here" parsed as BLOCK before #28."""
        raw = f"""
## Bad
- Nothing critical here. No security concerns, no data loss, nothing breaking.

{verdict_block("PASS")}
"""
        result = parser.parse_verdict(raw, "engineer")
        assert result.severity == "PASS"

    def test_real_damage_without_a_keyword_still_blocks(self, parser: VerdictParser) -> None:
        """A ledger the change deletes on restart parsed as WARN before #28."""
        raw = f"""
## Bad
- This deletes the ledger on restart.

{verdict_block("BLOCK", blocking=["Deletes the ledger on restart (invariant: data_validation)"])}
"""
        result = parser.parse_verdict(raw, "sre")
        assert result.severity == "BLOCK"

    def test_ugly_bucket_does_not_promote_severity(self, parser: VerdictParser) -> None:
        """An Ugly section full of scary words no longer forces BLOCK."""
        raw = f"""
## Ugly
- Security risk phrasing, data corruption phrasing, production failure phrasing.

{verdict_block("WARN", warnings=["Phrasing in the docstring is alarming"])}
"""
        result = parser.parse_verdict(raw, "sre")
        assert result.severity == "WARN"


class TestNoKeywordSeverity:
    """LESSON 11: forbid the removed mechanism with a test, not a comment."""

    def test_determine_severity_is_gone(self) -> None:
        """The inferring entry point must not come back."""
        assert not hasattr(VerdictParser, "_determine_severity")

    def test_no_keyword_table_in_source(self) -> None:
        """No list of magic words may decide severity in this module again.

        The module docstring names the old keywords so the failure mode stays
        readable, so this checks for the *mechanism* -- the named table and the
        function that consulted it -- rather than for the words themselves.
        """
        source = inspect.getsource(verdicts_module)
        for banned in ("block_indicators", "_determine_severity"):
            assert banned not in source, f"keyword-severity mechanism reintroduced: {banned}"


class TestVerdictParseError:
    """Test VerdictParseError exception."""

    def test_verdict_parse_error_instantiation(self) -> None:
        """Test VerdictParseError can be instantiated."""
        error = VerdictParseError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)


class TestFinding:
    """Test Finding model."""

    def test_finding_creation(self) -> None:
        """Test Finding model creation."""
        finding = Finding(
            bucket="bad", text="Test finding", severity="WARN", invariant_id="test_invariant"
        )
        assert finding.bucket == "bad"
        assert finding.text == "Test finding"
        assert finding.severity == "WARN"
        assert finding.invariant_id == "test_invariant"

    def test_finding_null_invariant(self) -> None:
        """Test Finding with null invariant_id."""
        finding = Finding(
            bucket="ugly",
            text="Test finding without invariant",
            severity="BLOCK",
            invariant_id=None,
        )
        assert finding.invariant_id is None


class TestParsedVerdict:
    """Test ParsedVerdict model."""

    def test_parsed_verdict_creation(self) -> None:
        """Test ParsedVerdict model creation."""
        findings = [
            Finding(bucket="bad", text="Issue 1", severity="WARN", invariant_id=None),
            Finding(bucket="ugly", text="Issue 2", severity="BLOCK", invariant_id="test_id"),
        ]

        verdict = ParsedVerdict(
            reviewer="engineer",
            severity="BLOCK",
            good="Good stuff",
            bad="Bad stuff",
            ugly="Ugly stuff",
            closing_question="Question?",
            findings=findings,
        )

        assert verdict.reviewer == "engineer"
        assert verdict.severity == "BLOCK"
        assert verdict.good == "Good stuff"
        assert verdict.bad == "Bad stuff"
        assert verdict.ugly == "Ugly stuff"
        assert verdict.closing_question == "Question?"
        assert len(verdict.findings) == 2
