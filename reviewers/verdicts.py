"""Good/Bad/Ugly parsing and invariant citation extraction for reviewer verdicts.

This module parses structured reviewer responses into normalized findings that can be
stored in the Verdict Store. It validates invariant citations against the project's
declared invariant list and extracts severity levels from verdict content.

Domain warnings:
⚠️ WARNING: Invariant citation fabrication — Validate cited IDs against project's declared invariant list
⚠️ WARNING: Invariant citation syntax — (invariant: <id>) inline citations extracted to findings.invariant_id
⚠️ WARNING: Unknown invariant IDs logged as warning, not error, with invariant_id set to None
"""

import re

import structlog
from pydantic import BaseModel

__all__ = ["Finding", "ParsedVerdict", "VerdictParseError", "VerdictParser"]

logger = structlog.get_logger(__name__)


class VerdictParseError(Exception):
    """Raised when verdict parsing fails."""

    pass


class Finding(BaseModel):
    """A discrete finding extracted from a verdict's bad or ugly bucket."""

    bucket: str  # bad | ugly
    text: str
    severity: str  # BLOCK | WARN
    invariant_id: str | None


class ParsedVerdict(BaseModel):
    """Structured verdict data extracted from raw reviewer response."""

    reviewer: str
    severity: str  # BLOCK | WARN | PASS
    good: str | None
    bad: str | None
    ugly: str | None
    closing_question: str | None
    findings: list[Finding]


class VerdictParser:
    """Parser for extracting structured data from reviewer verdict responses."""

    def __init__(self, project_invariants: list[str]) -> None:
        """Initialize parser with project-specific invariant validation.

        Args:
            project_invariants: List of valid invariant IDs for the project
        """
        self.project_invariants = set(project_invariants)
        logger.info(
            "VerdictParser initialized",
            invariant_count=len(project_invariants),
            invariant_ids=list(project_invariants),
        )

    def parse_verdict(self, raw_response: str, reviewer: str) -> ParsedVerdict:
        """Parse raw reviewer response into structured verdict data.

        Args:
            raw_response: Raw text response from reviewer
            reviewer: Name of the reviewer (engineer, architect, sre)

        Returns:
            ParsedVerdict with extracted sections and findings

        Raises:
            VerdictParseError: If response structure is malformed or unparseable
        """
        logger.info("Parsing verdict", reviewer=reviewer, response_length=len(raw_response))

        try:
            # Extract sections using regex patterns
            good = self._extract_section(raw_response, "Good")
            bad = self._extract_section(raw_response, "Bad")
            ugly = self._extract_section(raw_response, "Ugly")
            closing_question = self._extract_section(raw_response, "Closing Question")

            # Determine overall severity from bad/ugly content
            severity = self._determine_severity(bad, ugly)

            # Extract findings from bad and ugly buckets
            findings = []
            if bad:
                findings.extend(self._extract_findings(bad, "bad"))
            if ugly:
                findings.extend(self._extract_findings(ugly, "ugly"))

            logger.info(
                "Verdict parsed successfully",
                reviewer=reviewer,
                severity=severity,
                findings_count=len(findings),
                has_good=bool(good),
                has_bad=bool(bad),
                has_ugly=bool(ugly),
                has_closing_question=bool(closing_question),
            )

            return ParsedVerdict(
                reviewer=reviewer,
                severity=severity,
                good=good,
                bad=bad,
                ugly=ugly,
                closing_question=closing_question,
                findings=findings,
            )

        except Exception as e:
            logger.error(
                "Verdict parsing failed",
                reviewer=reviewer,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise VerdictParseError(f"Failed to parse verdict for {reviewer}: {e}") from e

    def _extract_section(self, content: str, section_name: str) -> str | None:
        """Extract content from a markdown section.

        Args:
            content: Full response content
            section_name: Section header to find (e.g., "Good", "Bad", "Ugly")

        Returns:
            Section content as string, or None if section not found
        """
        # Split content into lines for line-by-line processing
        lines = content.split("\n")
        section_start_pattern = rf"^\s*##\s*{re.escape(section_name)}\s*$"
        section_header_pattern = r"^\s*##\s*"

        section_lines: list[str] = []
        in_section = False

        for line in lines:
            # Check if this line starts our target section
            if re.match(section_start_pattern, line, re.IGNORECASE):
                in_section = True
                continue

            # Check if this line starts any other section (exit our section)
            if in_section and re.match(section_header_pattern, line):
                break

            # Collect lines if we're in our target section
            if in_section:
                section_lines.append(line)

        if section_lines:
            section_content = "\n".join(section_lines).strip()
            if section_content and not section_content.isspace():
                return section_content

        return None

    def _determine_severity(self, bad: str | None, ugly: str | None) -> str:
        """Determine overall verdict severity from bad/ugly content.

        Args:
            bad: Content of the "Bad" section
            ugly: Content of the "Ugly" section

        Returns:
            Severity level: BLOCK, WARN, or PASS
        """
        # Check for blocking keywords in bad section
        if bad:
            bad_lower = bad.lower()
            block_indicators = [
                "block",
                "breaking",
                "security",
                "data loss",
                "corrupts",
                "irreversible",
                "critical",
            ]
            if any(indicator in bad_lower for indicator in block_indicators):
                return "BLOCK"

        # Check for blocking keywords in ugly section
        if ugly:
            ugly_lower = ugly.lower()
            block_indicators = [
                "block",
                "security risk",
                "data corruption",
                "production failure",
                "rollback required",
            ]
            if any(indicator in ugly_lower for indicator in block_indicators):
                return "BLOCK"

        # If we have findings but no blocking issues, it's a warning
        if bad or ugly:
            return "WARN"

        # No issues found
        return "PASS"

    def _extract_findings(self, section_content: str, bucket: str) -> list[Finding]:
        """Extract discrete findings from a section.

        Args:
            section_content: Content of bad or ugly section
            bucket: Section name ("bad" or "ugly")

        Returns:
            List of Finding objects extracted from the section
        """
        findings = []

        # Split content into individual findings (typically bullet points)
        lines = section_content.split("\n")
        current_finding: list[str] = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check if this line starts a new finding (bullet point or dash)
            if line.startswith(("- ", "* ", "• ")) or (
                not current_finding and line and not line.startswith(" ")
            ):
                # Process previous finding if exists
                if current_finding:
                    finding_text = " ".join(current_finding).strip()
                    if finding_text:
                        finding = self._create_finding(finding_text, bucket)
                        findings.append(finding)

                # Start new finding
                # Remove bullet point markers
                clean_line = re.sub(r"^[-*•]\s*", "", line)
                current_finding = [clean_line]
            else:
                # Continuation of current finding
                if current_finding:
                    current_finding.append(line)

        # Process final finding
        if current_finding:
            finding_text = " ".join(current_finding).strip()
            if finding_text:
                finding = self._create_finding(finding_text, bucket)
                findings.append(finding)

        logger.debug("Extracted findings", bucket=bucket, count=len(findings))
        return findings

    def _create_finding(self, text: str, bucket: str) -> Finding:
        """Create a Finding object from text with invariant citation extraction.

        Args:
            text: Finding text that may contain invariant citations
            bucket: Source bucket ("bad" or "ugly")

        Returns:
            Finding object with extracted invariant citation
        """
        # Extract invariant citations using pattern: (invariant: <id>)
        invariant_pattern = r"\(invariant:\s*([^)]+)\)"
        match = re.search(invariant_pattern, text, re.IGNORECASE)

        invariant_id = None
        if match:
            cited_id = match.group(1).strip()
            if cited_id in self.project_invariants:
                invariant_id = cited_id
                logger.debug("Valid invariant citation found", invariant_id=invariant_id)
            else:
                logger.warning(
                    "Invalid invariant citation found",
                    cited_id=cited_id,
                    valid_invariants=list(self.project_invariants),
                )

        # Determine finding-level severity
        text_lower = text.lower()
        if bucket == "ugly" or any(
            keyword in text_lower for keyword in ["block", "critical", "security", "data loss"]
        ):
            severity = "BLOCK"
        else:
            severity = "WARN"

        return Finding(
            bucket=bucket,
            text=text,
            severity=severity,
            invariant_id=invariant_id,
        )
