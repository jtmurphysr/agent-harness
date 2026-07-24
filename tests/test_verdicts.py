"""Tests for reviewers.verdicts module."""

import pytest

from reviewers.verdicts import Finding, ParsedVerdict, VerdictParseError, VerdictParser


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


class TestParseVerdict:
    """Test verdict parsing functionality."""

    @pytest.fixture
    def parser(self) -> VerdictParser:
        """Create parser with test invariants."""
        return VerdictParser(["auth_required", "soft_delete_filter", "data_validation"])

    def test_parse_verdict_good_bad_ugly_structure(self, parser: VerdictParser) -> None:
        """Test parsing of Good/Bad/Ugly structured response."""
        raw_response = """
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
"""
        result = parser.parse_verdict(raw_response, "engineer")

        assert result.reviewer == "engineer"
        assert result.good == "- Code follows established patterns\n- Tests are included\n- Documentation is comprehensive"
        assert result.bad == "- Minor style inconsistencies in function names\n- Missing type hints in helper functions"
        assert result.ugly == "- No major architectural concerns"
        assert result.closing_question == "Have you considered the performance implications of this change?"
        assert result.severity == "WARN"  # Has issues but not blocking
        assert len(result.findings) == 3

    def test_parse_verdict_invariant_citations_extracted(self, parser: VerdictParser) -> None:
        """Test invariant citation extraction from findings."""
        raw_response = """
## Bad
- Authentication bypass detected in login route (invariant: auth_required)
- Soft-delete filter missing on user query (invariant: soft_delete_filter)

## Ugly
- Data validation skipped on input processing (invariant: data_validation)
"""
        result = parser.parse_verdict(raw_response, "sre")

        assert len(result.findings) == 3
        
        # Check first finding
        auth_finding = next(f for f in result.findings if f.invariant_id == "auth_required")
        assert auth_finding.bucket == "bad"
        assert "Authentication bypass detected" in auth_finding.text
        assert auth_finding.severity == "WARN"

        # Check second finding
        delete_finding = next(f for f in result.findings if f.invariant_id == "soft_delete_filter")
        assert delete_finding.bucket == "bad"
        assert "Soft-delete filter missing" in delete_finding.text

        # Check third finding
        validation_finding = next(f for f in result.findings if f.invariant_id == "data_validation")
        assert validation_finding.bucket == "ugly"
        assert "Data validation skipped" in validation_finding.text

    def test_parse_verdict_invalid_invariant_id_nulled(self, parser: VerdictParser) -> None:
        """Test that invalid invariant IDs are set to None with warning logged."""
        raw_response = """
## Bad
- Security issue found (invariant: nonexistent_rule)
- Valid issue (invariant: auth_required)
"""
        result = parser.parse_verdict(raw_response, "architect")

        assert len(result.findings) == 2
        
        # First finding should have null invariant_id
        invalid_finding = next(f for f in result.findings if "nonexistent_rule" in f.text)
        assert invalid_finding.invariant_id is None
        
        # Second finding should have valid invariant_id
        valid_finding = next(f for f in result.findings if "Valid issue" in f.text)
        assert valid_finding.invariant_id == "auth_required"

    def test_parse_verdict_severity_detection(self, parser: VerdictParser) -> None:
        """Test severity detection from response content."""
        # Test BLOCK severity
        blocking_response = """
## Bad
- This change will cause data loss
- Security vulnerability detected

## Ugly
- No major issues
"""
        result = parser.parse_verdict(blocking_response, "engineer")
        assert result.severity == "BLOCK"

        # Test WARN severity
        warning_response = """
## Bad
- Minor style issues

## Ugly
- Performance could be improved
"""
        result = parser.parse_verdict(warning_response, "engineer")
        assert result.severity == "WARN"

        # Test PASS severity
        passing_response = """
## Good
- Excellent implementation
- All tests pass

## Closing Question
Any concerns about deployment timing?
"""
        result = parser.parse_verdict(passing_response, "engineer")
        assert result.severity == "PASS"

    def test_parse_verdict_findings_parsed(self, parser: VerdictParser) -> None:
        """Test finding extraction and normalization."""
        raw_response = """
## Bad
- Issue 1: First problem
- Issue 2: Second problem with details

## Ugly
- Critical security flaw requires immediate attention
- Performance bottleneck detected
"""
        result = parser.parse_verdict(raw_response, "sre")

        assert len(result.findings) == 4
        
        # Check bad findings
        bad_findings = [f for f in result.findings if f.bucket == "bad"]
        assert len(bad_findings) == 2
        assert bad_findings[0].text == "Issue 1: First problem"
        assert bad_findings[0].severity == "WARN"
        assert bad_findings[1].text == "Issue 2: Second problem with details"

        # Check ugly findings
        ugly_findings = [f for f in result.findings if f.bucket == "ugly"]
        assert len(ugly_findings) == 2
        assert ugly_findings[0].text == "Critical security flaw requires immediate attention"
        assert ugly_findings[0].severity == "BLOCK"  # "security" keyword triggers BLOCK
        assert ugly_findings[1].text == "Performance bottleneck detected"

    def test_parse_verdict_malformed_response(self, parser: VerdictParser) -> None:
        """Test handling of malformed responses."""
        malformed_response = "This is not a structured response"
        
        # Should not raise exception, but should handle gracefully
        result = parser.parse_verdict(malformed_response, "engineer")
        assert result.reviewer == "engineer"
        assert result.good is None
        assert result.bad is None
        assert result.ugly is None
        assert result.closing_question is None
        assert result.severity == "PASS"  # No findings means PASS
        assert len(result.findings) == 0

    def test_parse_verdict_missing_sections(self, parser: VerdictParser) -> None:
        """Test parsing when some sections are missing."""
        partial_response = """
## Good
- Implementation looks solid

## Closing Question
What about error handling?
"""
        result = parser.parse_verdict(partial_response, "architect")

        assert result.good == "- Implementation looks solid"
        assert result.bad is None
        assert result.ugly is None
        assert result.closing_question == "What about error handling?"
        assert result.severity == "PASS"
        assert len(result.findings) == 0

    def test_parse_verdict_case_insensitive_sections(self, parser: VerdictParser) -> None:
        """Test that section headers are case-insensitive."""
        mixed_case_response = """
## good
- This is good

## BAD
- This is bad

## Ugly
- This is ugly

## closing question
What do you think?
"""
        result = parser.parse_verdict(mixed_case_response, "engineer")

        assert result.good == "- This is good"
        assert result.bad == "- This is bad"
        assert result.ugly == "- This is ugly"
        assert result.closing_question == "What do you think?"

    def test_parse_verdict_multiline_findings(self, parser: VerdictParser) -> None:
        """Test parsing of multi-line findings."""
        multiline_response = """
## Bad
- Complex issue that spans
  multiple lines and needs
  detailed explanation
- Simple single line issue

## Ugly
- Another multi-line finding
  with continuation
  across several lines
"""
        result = parser.parse_verdict(multiline_response, "engineer")

        assert len(result.findings) == 3
        
        # Check multi-line finding
        complex_finding = next(f for f in result.findings if "Complex issue" in f.text)
        expected_text = "Complex issue that spans multiple lines and needs detailed explanation"
        assert complex_finding.text == expected_text

        # Check single line finding
        simple_finding = next(f for f in result.findings if "Simple single line" in f.text)
        assert simple_finding.text == "Simple single line issue"

    def test_parse_verdict_block_severity_keywords(self, parser: VerdictParser) -> None:
        """Test that specific keywords trigger BLOCK severity."""
        block_keywords = [
            ("breaking change", "BLOCK"),
            ("security vulnerability", "BLOCK"),
            ("data loss", "BLOCK"),
            ("corrupts database", "BLOCK"),
            ("irreversible", "BLOCK"),
            ("critical failure", "BLOCK"),
        ]
        
        for keyword, expected_severity in block_keywords:
            response = f"""
## Bad
- This change causes {keyword}
"""
            result = parser.parse_verdict(response, "sre")
            assert result.severity == expected_severity, f"Keyword '{keyword}' should trigger {expected_severity}"

    def test_parse_verdict_ugly_block_keywords(self, parser: VerdictParser) -> None:
        """Test BLOCK keywords in ugly section."""
        ugly_block_response = """
## Ugly
- Security risk in authentication flow
- Data corruption possible in edge case
- Production failure likely under load
"""
        result = parser.parse_verdict(ugly_block_response, "sre")
        assert result.severity == "BLOCK"

    def test_parse_verdict_empty_sections_ignored(self, parser: VerdictParser) -> None:
        """Test that empty sections are treated as None."""
        empty_sections_response = """
## Good

## Bad
- Actual issue here

## Ugly


## Closing Question
"""
        result = parser.parse_verdict(empty_sections_response, "engineer")

        assert result.good is None  # Empty section
        assert result.bad == "- Actual issue here"
        assert result.ugly is None  # Empty section
        assert result.closing_question is None  # Empty section
        assert result.severity == "WARN"

    def test_parse_verdict_invariant_citation_case_insensitive(self, parser: VerdictParser) -> None:
        """Test invariant citation parsing is case-insensitive."""
        response = """
## Bad
- Issue found (INVARIANT: auth_required)
- Another issue (Invariant: soft_delete_filter)
"""
        result = parser.parse_verdict(response, "engineer")

        findings_with_invariants = [f for f in result.findings if f.invariant_id is not None]
        assert len(findings_with_invariants) == 2
        assert any(f.invariant_id == "auth_required" for f in findings_with_invariants)
        assert any(f.invariant_id == "soft_delete_filter" for f in findings_with_invariants)


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
            bucket="bad",
            text="Test finding",
            severity="WARN",
            invariant_id="test_invariant"
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
            invariant_id=None
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
            findings=findings
        )
        
        assert verdict.reviewer == "engineer"
        assert verdict.severity == "BLOCK"
        assert verdict.good == "Good stuff"
        assert verdict.bad == "Bad stuff"
        assert verdict.ugly == "Ugly stuff"
        assert verdict.closing_question == "Question?"
        assert len(verdict.findings) == 2