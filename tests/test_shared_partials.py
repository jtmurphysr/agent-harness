"""
Tests for templates/_shared/ partial files.

Validates that the partial files contain required sections and follow proper format.
"""

import re
from pathlib import Path


class TestSharedPartials:
    """Test suite for template partial files in templates/_shared/."""

    @property
    def shared_dir(self) -> Path:
        """Path to templates/_shared directory."""
        return Path(__file__).parent.parent / "templates" / "_shared"

    def test_output_contract_partial_valid(self):
        """Test that output_contract.partial.md contains required Good/Bad/Ugly sections."""
        output_contract_path = self.shared_dir / "output_contract.partial.md"
        assert output_contract_path.exists(), "output_contract.partial.md must exist"
        
        content = output_contract_path.read_text()
        
        # Check for required sections
        assert "### Good" in content, "Output contract must have 'Good' section"
        assert "### Bad" in content, "Output contract must have 'Bad' section" 
        assert "### Ugly" in content, "Output contract must have 'Ugly' section"
        assert "### Closing Question" in content, "Output contract must have 'Closing Question' section"
        
        # Check for severity levels
        assert "BLOCK" in content, "Output contract must reference BLOCK severity"
        assert "WARN" in content, "Output contract must reference WARN severity"
        assert "PASS" in content, "Output contract must reference PASS severity"
        
        # Check for citation protocol
        assert "(invariant: <id>)" in content, "Output contract must document invariant citation syntax"

    def test_refusal_conditions_partial_valid(self):
        """Test that refusal_conditions.partial.md contains security refusal patterns."""
        refusal_conditions_path = self.shared_dir / "refusal_conditions.partial.md"
        assert refusal_conditions_path.exists(), "refusal_conditions.partial.md must exist"
        
        content = refusal_conditions_path.read_text()
        
        # Check for security focus
        assert "DEFENSIVE SECURITY ONLY" in content, "Must specify defensive security focus"
        
        # Check for refusal conditions
        assert "Refusal Conditions" in content, "Must have refusal conditions section"
        assert "Malicious Intent" in content, "Must address malicious intent detection"
        
        # Check for response protocol
        assert "Response Protocol" in content, "Must have response protocol for refusals"
        assert "I cannot provide feedback" in content, "Must include refusal template text"
        
        # Check for security categories
        assert "backdoor" in content.lower() or "Backdoor" in content, "Must address backdoor detection"

    def test_posture_directives_partial_valid(self):
        """Test that posture_directives.partial.md contains behavioral directives."""
        posture_directives_path = self.shared_dir / "posture_directives.partial.md"
        assert posture_directives_path.exists(), "posture_directives.partial.md must exist"
        
        content = posture_directives_path.read_text()
        
        # Check for blind parallel execution
        assert "BLIND PARALLEL EXECUTION" in content, "Must specify blind parallel execution"
        assert "independently" in content.lower(), "Must emphasize independence"
        
        # Check for core behavioral elements
        assert "Independence" in content, "Must address independence principle"
        assert "Completeness" in content, "Must address completeness principle"
        assert "Specificity" in content, "Must address specificity principle"
        
        # Check for review standards
        assert "Review Scope" in content, "Must define review scope standards"
        assert "Finding Quality" in content, "Must define finding quality standards"

    def test_all_partials_jinja2_syntax(self):
        """Test that all partials use valid Jinja2 include syntax."""
        for partial_file in self.shared_dir.glob("*.partial.md"):
            content = partial_file.read_text()
            
            # Check for valid Jinja2 variable syntax
            jinja_vars = re.findall(r"\{\{[^}]+\}\}", content)
            for var in jinja_vars:
                # Variables should have proper spacing and valid identifiers
                inner = var.strip("{}").strip()
                assert re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$", inner), \
                    f"Invalid Jinja2 variable syntax in {partial_file.name}: {var}"
            
            # Check that file is ready for Jinja2 include (has proper structure)
            assert not content.strip().startswith("{% include"), \
                f"Partial {partial_file.name} should not contain include statements (it IS the included content)"

    def test_version_frontmatter_format(self):
        """Test that version frontmatter follows required pattern."""
        version_pattern = r'^---\nversion: "(\d+\.\d+\.\d+)"\n---'
        
        for partial_file in self.shared_dir.glob("*.partial.md"):
            content = partial_file.read_text()
            
            # Check for frontmatter presence
            assert content.startswith("---\n"), \
                f"File {partial_file.name} must start with YAML frontmatter"
            
            # Check for proper version format
            match = re.search(version_pattern, content, re.MULTILINE)
            assert match, \
                f"File {partial_file.name} must have version frontmatter in format: version: \"X.Y.Z\""
            
            # Validate semantic version format
            version = match.group(1)
            parts = version.split(".")
            assert len(parts) == 3, f"Version must have 3 parts: {version}"
            assert all(part.isdigit() for part in parts), f"Version parts must be numeric: {version}"