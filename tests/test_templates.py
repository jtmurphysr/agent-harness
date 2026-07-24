"""
Tests for templates/engineer.template.md, architect.template.md, and sre.template.md.

Validates that the template files contain required sections, proper Jinja2 syntax,
version frontmatter, and include directives for shared partials.
"""

import re
import yaml
from pathlib import Path


class TestTemplates:
    """Test suite for role-specific template files."""

    @property
    def templates_dir(self) -> Path:
        """Path to templates directory."""
        return Path(__file__).parent.parent / "templates"

    def _load_template(self, template_name: str) -> tuple[dict, str]:
        """Load a template file and return (frontmatter, content)."""
        template_path = self.templates_dir / f"{template_name}.template.md"
        assert template_path.exists(), f"{template_name}.template.md must exist"
        
        content = template_path.read_text()
        
        # Parse frontmatter
        assert content.startswith("---\n"), f"{template_name}.template.md must start with YAML frontmatter"
        
        parts = content.split("---\n", 2)
        assert len(parts) >= 3, f"{template_name}.template.md must have complete frontmatter"
        
        frontmatter_text = parts[1]
        body_content = parts[2]
        
        frontmatter = yaml.safe_load(frontmatter_text)
        return frontmatter, body_content

    def test_engineer_template_loads_valid_yaml_frontmatter(self):
        """Test that engineer.template.md has valid YAML frontmatter."""
        frontmatter, _ = self._load_template("engineer")
        
        # Required frontmatter fields
        assert "version" in frontmatter, "engineer template must have version field"
        assert "propagation" in frontmatter, "engineer template must have propagation field"
        
        # Version format validation
        version = frontmatter["version"]
        assert isinstance(version, str), "Version must be a string"
        assert re.match(r"^\d+\.\d+\.\d+$", version), f"Version must be semantic version format: {version}"
        
        # Propagation validation  
        propagation = frontmatter["propagation"]
        assert propagation in ["auto", "opt_in", "security"], f"Invalid propagation value: {propagation}"

    def test_architect_template_loads_valid_yaml_frontmatter(self):
        """Test that architect.template.md has valid YAML frontmatter."""
        frontmatter, _ = self._load_template("architect")
        
        # Required frontmatter fields
        assert "version" in frontmatter, "architect template must have version field"
        assert "propagation" in frontmatter, "architect template must have propagation field"
        
        # Version format validation
        version = frontmatter["version"]
        assert isinstance(version, str), "Version must be a string"
        assert re.match(r"^\d+\.\d+\.\d+$", version), f"Version must be semantic version format: {version}"
        
        # Propagation validation
        propagation = frontmatter["propagation"]
        assert propagation in ["auto", "opt_in", "security"], f"Invalid propagation value: {propagation}"

    def test_sre_template_loads_valid_yaml_frontmatter(self):
        """Test that sre.template.md has valid YAML frontmatter."""
        frontmatter, _ = self._load_template("sre")
        
        # Required frontmatter fields
        assert "version" in frontmatter, "sre template must have version field"
        assert "propagation" in frontmatter, "sre template must have propagation field"
        
        # Version format validation
        version = frontmatter["version"]
        assert isinstance(version, str), "Version must be a string"
        assert re.match(r"^\d+\.\d+\.\d+$", version), f"Version must be semantic version format: {version}"
        
        # Propagation validation
        propagation = frontmatter["propagation"]
        assert propagation in ["auto", "opt_in", "security"], f"Invalid propagation value: {propagation}"

    def test_templates_include_shared_partials(self):
        """Test that all templates include shared partial files."""
        expected_includes = [
            "_shared/posture_directives.partial.md",
            "_shared/output_contract.partial.md", 
            "_shared/refusal_conditions.partial.md"
        ]
        
        for template_name in ["engineer", "architect", "sre"]:
            _, content = self._load_template(template_name)
            
            for expected_include in expected_includes:
                include_pattern = f"{{%\\s*include\\s+['\"]?{re.escape(expected_include)}['\"]?\\s*%}}"
                assert re.search(include_pattern, content), \
                    f"{template_name}.template.md must include {expected_include}"

    def test_templates_contain_jinja2_variables(self):
        """Test that all templates contain Jinja2 variable injection points."""
        # Variables that should be in all templates
        common_variables = [
            "project.name",
            "project.description", 
            "deployment.surface"
        ]
        
        # Template-specific variable requirements
        template_variables = {
            "engineer": ["stack.language", "invariants", "stack.framework"],
            "architect": ["stack.language", "invariants", "becoming"],
            "sre": ["deployment.surface", "invariants", "stack.database"]
        }
        
        for template_name in ["engineer", "architect", "sre"]:
            _, content = self._load_template(template_name)
            
            # Check common variables
            for expected_var in common_variables:
                assert expected_var in content, \
                    f"{template_name}.template.md must contain Jinja2 variable: {expected_var}"
            
            # Check template-specific variables (at least some should be present)
            specific_vars = template_variables.get(template_name, [])
            found_vars = [var for var in specific_vars if var in content]
            assert len(found_vars) > 0, \
                f"{template_name}.template.md must contain at least one specific variable from: {specific_vars}"
            
            # Check for proper Jinja2 loop syntax
            assert "{% for" in content, f"{template_name}.template.md must contain Jinja2 loops"
            assert "{% endfor %}" in content, f"{template_name}.template.md must have closed Jinja2 loops"
            
            # Check for conditional syntax
            assert "{% if" in content, f"{template_name}.template.md must contain Jinja2 conditionals"
            assert "{% endif %}" in content, f"{template_name}.template.md must have closed Jinja2 conditionals"

    def test_templates_version_frontmatter_present(self):
        """Test that all templates have proper version frontmatter."""
        for template_name in ["engineer", "architect", "sre"]:
            frontmatter, _ = self._load_template(template_name)
            
            # Version field must exist
            assert "version" in frontmatter, f"{template_name}.template.md must have version frontmatter"
            
            # Version must be semantic version string
            version = frontmatter["version"]
            assert isinstance(version, str), f"{template_name} version must be string, got {type(version)}"
            assert re.match(r"^\d+\.\d+\.\d+$", version), f"{template_name} version must be X.Y.Z format: {version}"

    def test_templates_role_specific_sections(self):
        """Test that each template contains role-specific sections."""
        # Engineer-specific sections
        _, engineer_content = self._load_template("engineer")
        assert "implementation level" in engineer_content.lower(), "Engineer must focus on implementation"
        assert "correctness" in engineer_content.lower(), "Engineer must address correctness"
        
        # Architect-specific sections  
        _, architect_content = self._load_template("architect")
        assert "conceptual level" in architect_content.lower(), "Architect must focus on conceptual level"
        assert "boundary" in architect_content.lower(), "Architect must address boundaries"
        assert "abstraction" in architect_content.lower(), "Architect must address abstractions"
        
        # SRE-specific sections
        _, sre_content = self._load_template("sre")
        assert "production safety" in sre_content.lower(), "SRE must focus on production safety"
        assert "operational" in sre_content.lower(), "SRE must address operational concerns"
        assert "failure mode" in sre_content.lower(), "SRE must analyze failure modes"

    def test_templates_have_project_context_integration(self):
        """Test that templates properly integrate project context variables."""
        for template_name in ["engineer", "architect", "sre"]:
            _, content = self._load_template(template_name)
            
            # Check for project context sections
            assert "Project Context" in content, f"{template_name} must have Project Context section"
            
            # Check for context variable usage
            context_vars = [
                "{{ project.name }}",
                "{{ project.description }}",
                "{{ stack.language }}",
                "{{ deployment.surface }}"
            ]
            
            for var in context_vars:
                assert var in content, f"{template_name} must use project context variable: {var}"

    def test_templates_validate_jinja2_syntax(self):
        """Test that all Jinja2 syntax in templates is valid."""
        jinja2_patterns = [
            (r"\{\{[^}]+\}\}", "Variable syntax"),
            (r"\{%[^%]+%\}", "Control structure syntax"),
            (r"\{#[^#]+#\}", "Comment syntax")
        ]
        
        for template_name in ["engineer", "architect", "sre"]:
            _, content = self._load_template(template_name)
            
            for pattern, description in jinja2_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    # Check for proper spacing
                    assert not match.startswith("{{") or " " in match[:4], \
                        f"{template_name}: {description} should have space after opening: {match}"
                    assert not match.endswith("}}") or " " in match[-4:], \
                        f"{template_name}: {description} should have space before closing: {match}"