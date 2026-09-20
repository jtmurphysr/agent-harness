"""Literal parsing of the reviewer verdict block, plus Good/Bad/Ugly sections.

A reviewer's response ends with a mandatory block, defined in
`templates/_shared/verdict_block.partial.md`:

    ## Verdict
    VERDICT: PASS | WARN | BLOCK
    BLOCKING:
    - <one finding per line> (invariant: <id> | spec: <section> | scope: <issue section>)
    WARNINGS:
    - <one finding per line>

This module reads that block **literally**. Severity is the word on the
`VERDICT:` line and nothing else.

WHY THIS IS LITERAL: until #28 there was no contract between what the templates
asked for and what this parser read. The templates specified no output format at
all, and severity was inferred by sniffing the Bad section for "block",
"critical", "security", "breaking", "data loss", "corrupts", "irreversible".
"Nothing critical here" parsed as BLOCK. "This deletes the ledger on restart",
having dodged every magic word, parsed as WARN. Both directions were wrong and
neither was visible in the output. Do not reintroduce a keyword table here;
`tests/test_verdicts.py::TestNoKeywordSeverity` fails if one comes back.

Rules, enforced here and stated in the template:

- The `VERDICT:` line is required. Absent, or carrying anything other than
  exactly PASS / WARN / BLOCK, raises VerdictParseError. Callers treat a parse
  error as a failed review, never as a PASS -- a reviewer must not be able to
  pass a change by going silent or by echoing the template.
- BLOCK is legal only if at least one BLOCKING line carries a citation:
  `(invariant: <id>)`, `(spec: <section>)` or `(scope: <section>)`. A BLOCK with
  no citable finding is a parse error. This is what keeps BLOCK off taste.
- WARN requires at least one WARNINGS line. PASS requires both lists empty.
- An `(invariant: <id>)` citation naming an id the project has not declared is a
  parse error. The parser is handed the declared list; an id outside it is a
  fabrication, and a fabricated citation is exactly what the citation
  requirement exists to prevent. `spec:` and `scope:` citations name sections of
  documents the parser is not given, so their text is required but not verified.
"""

import re

import structlog
from pydantic import BaseModel

__all__ = ["Finding", "ParsedVerdict", "VerdictParseError", "VerdictParser"]

logger = structlog.get_logger(__name__)

#: The only three words the VERDICT line may carry.
LEGAL_VERDICTS = frozenset({"PASS", "WARN", "BLOCK"})

#: The citation forms a BLOCKING line may use to earn a BLOCK.
CITATION_KINDS = frozenset({"invariant", "spec", "scope"})

_VERDICT_LINE = re.compile(r"^[ \t]*VERDICT:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_LIST_LABEL = re.compile(r"^[ \t]*(BLOCKING|WARNINGS):[ \t]*(.*)$", re.IGNORECASE)
_BULLET = re.compile(r"^[ \t]*[-*•][ \t]+(.*)$")
_CITATION = re.compile(r"\((invariant|spec|scope):\s*([^)]*)\)", re.IGNORECASE)


class VerdictParseError(Exception):
    """Raised when verdict parsing fails.

    The caller must treat this as a failed review. It is never a PASS.
    """

    pass


class Finding(BaseModel):
    """A discrete finding taken from the BLOCKING or WARNINGS list."""

    bucket: str  # bad (from BLOCKING) | ugly (from WARNINGS)
    text: str
    severity: str  # BLOCK | WARN
    invariant_id: str | None


class ParsedVerdict(BaseModel):
    """Structured verdict data extracted from a raw reviewer response."""

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
            ParsedVerdict with the declared severity, the prose sections, and one
            Finding per BLOCKING/WARNINGS line

        Raises:
            VerdictParseError: If the verdict block is absent or violates the
                contract in templates/_shared/verdict_block.partial.md
        """
        logger.info("Parsing verdict", reviewer=reviewer, response_length=len(raw_response))

        try:
            good = self._extract_section(raw_response, "Good")
            bad = self._extract_section(raw_response, "Bad")
            ugly = self._extract_section(raw_response, "Ugly")
            closing_question = self._extract_section(raw_response, "Closing Question")

            severity, findings = self._parse_verdict_block(raw_response)

        except VerdictParseError:
            # Already carries the specific contract violation; re-wrapping would
            # bury it under a generic message.
            logger.error("Verdict parsing failed", reviewer=reviewer)
            raise
        except Exception as e:
            logger.error(
                "Verdict parsing failed",
                reviewer=reviewer,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise VerdictParseError(f"Failed to parse verdict for {reviewer}: {e}") from e

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

    def _parse_verdict_block(self, content: str) -> tuple[str, list[Finding]]:
        """Read the mandatory verdict block and return (severity, findings).

        Args:
            content: The full reviewer response

        Returns:
            The declared severity and the findings from both lists

        Raises:
            VerdictParseError: On any violation of the verdict contract
        """
        matches = list(_VERDICT_LINE.finditer(content))
        if not matches:
            raise VerdictParseError(
                "no VERDICT: line in the response. Every review must end with the "
                "verdict block; see templates/_shared/verdict_block.partial.md. "
                "A missing verdict is a failed review, not a PASS."
            )

        # The LAST occurrence: a reviewer that quotes the contract before
        # answering leaves the literal `VERDICT: PASS | WARN | BLOCK` upstream,
        # and the block is specified to be the end of the response.
        verdict_match = matches[-1]
        declared = verdict_match.group(1).strip().upper()
        if declared not in LEGAL_VERDICTS:
            raise VerdictParseError(
                f"VERDICT line carries {declared!r}; it must be exactly one of "
                f"{', '.join(sorted(LEGAL_VERDICTS))}. Leaving the literal "
                f"'PASS | WARN | BLOCK' in place is a parse failure, not a PASS."
            )

        blocking, warnings = self._extract_lists(content[verdict_match.end() :])

        if declared == "BLOCK":
            if not blocking:
                raise VerdictParseError(
                    "VERDICT: BLOCK with an empty BLOCKING list. A block must name "
                    "what it blocks on."
                )
            if not any(self._citation(line) for line in blocking):
                raise VerdictParseError(
                    "VERDICT: BLOCK with no citable BLOCKING finding. At least one "
                    "BLOCKING line must carry (invariant: <id>), (spec: <section>) "
                    "or (scope: <section>). BLOCK is for what the project has "
                    "written down, not for taste."
                )
        elif declared == "WARN":
            if not warnings:
                raise VerdictParseError(
                    "VERDICT: WARN with an empty WARNINGS list. A warning must name "
                    "what it warns about."
                )
        else:  # PASS
            if blocking or warnings:
                raise VerdictParseError(
                    f"VERDICT: PASS with {len(blocking)} BLOCKING and "
                    f"{len(warnings)} WARNINGS line(s). PASS requires both lists "
                    f"empty; declare WARN or BLOCK instead."
                )

        findings = [self._create_finding(text, "bad", "BLOCK") for text in blocking]
        findings.extend(self._create_finding(text, "ugly", "WARN") for text in warnings)
        return declared, findings

    def _extract_lists(self, tail: str) -> tuple[list[str], list[str]]:
        """Split the text after the VERDICT line into the two finding lists.

        Bullets are collected under whichever label most recently appeared.
        Bullets that are still the template's `<placeholder>` text are dropped,
        so echoing the contract cannot manufacture a finding.

        Args:
            tail: Everything after the VERDICT line

        Returns:
            (blocking lines, warnings lines), each bullet's text with the marker
            stripped and any continuation lines joined
        """
        lists: dict[str, list[str]] = {"BLOCKING": [], "WARNINGS": []}
        current: str | None = None
        pending: list[str] = []

        for line in tail.split("\n"):
            label = _LIST_LABEL.match(line)
            if label:
                self._flush(lists, current, pending)
                current = label.group(1).upper()
                # `BLOCKING: none` -- a label with trailing text is not a bullet.
                continue

            bullet = _BULLET.match(line)
            if bullet:
                self._flush(lists, current, pending)
                pending.append(bullet.group(1))
                continue

            if not line.strip():
                self._flush(lists, current, pending)
                continue

            if pending:
                # Continuation of the bullet above it.
                pending.append(line)

        self._flush(lists, current, pending)
        return lists["BLOCKING"], lists["WARNINGS"]

    @staticmethod
    def _flush(lists: dict[str, list[str]], current: str | None, pending: list[str]) -> None:
        """Move the pending bullet into *current*'s list and clear it.

        Args:
            lists: The two accumulating lists, keyed BLOCKING / WARNINGS
            current: The label the pending bullet belongs to, or None if the
                bullet appeared before any label and should be dropped
            pending: The bullet's first line plus any continuation lines
        """
        if current is not None and pending:
            text = " ".join(part.strip() for part in pending).strip()
            # `<one finding per line>` is the template's placeholder, not a finding.
            if text and not text.startswith("<"):
                lists[current].append(text)
        pending.clear()

    def _citation(self, text: str) -> tuple[str, str] | None:
        """Return the (kind, value) of the first citation in *text*, if any.

        Args:
            text: A single finding line

        Returns:
            (kind, value) with kind lowercased, or None if uncited

        Raises:
            VerdictParseError: If an invariant citation names an id the project
                has not declared
        """
        match = _CITATION.search(text)
        if not match:
            return None

        kind = match.group(1).lower()
        value = match.group(2).strip()
        if not value:
            return None

        if kind == "invariant" and value not in self.project_invariants:
            raise VerdictParseError(
                f"finding cites invariant {value!r}, which this project has not "
                f"declared. Declared ids: "
                f"{', '.join(sorted(self.project_invariants)) or '(none)'}."
            )
        return kind, value

    def _create_finding(self, text: str, bucket: str, severity: str) -> Finding:
        """Build a Finding, attaching a validated invariant id when one is cited.

        Args:
            text: The finding line as written
            bucket: "bad" for BLOCKING lines, "ugly" for WARNINGS lines
            severity: "BLOCK" for BLOCKING lines, "WARN" for WARNINGS lines

        Returns:
            Finding with invariant_id set only for a declared invariant citation
        """
        citation = self._citation(text)
        invariant_id = citation[1] if citation and citation[0] == "invariant" else None
        return Finding(bucket=bucket, text=text, severity=severity, invariant_id=invariant_id)

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
