"""Tests for renderer/validators.py."""

import tempfile
from pathlib import Path

import pytest

from renderer.validators import ProjectContextError, validate_project_context


class TestValidateProjectContext:
    """Tests for validate_project_context function."""
    
    def test_validate_project_context_valid_schema(self, tmp_path: Path) -> None:
        """Test validation of a valid project context file."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  bundle_id: "com.example.test"
  description: "A test project for validation"

stack:
  language: "Python"
  framework: "FastAPI"
  database: "PostgreSQL"
  primary_files:
    high_blast_radius: ["app/core.py", "app/models.py"]
    generated: ["migrations/"]

deployment:
  surface: "server"
  stores: []
  rollback_available: true
  forced_update: false
  user_data_recoverable: true
  production_record_count: 1000

invariants:
  - id: "auth_required"
    rule: "All API endpoints require authentication"
    severity: "correctness"
  - id: "data_validation"
    rule: "All input data must be validated"
    severity: "data_consistency"

sharp_edges:
  - location: "app/auth.py"
    issue: "Token expiration not handled"
    fix: "Add token refresh logic"

structural_decisions:
  - decision: "Use FastAPI for web framework"
    rationale: "Strong typing and async support"

becoming:
  - "Add GraphQL support"
  - "Implement caching layer"

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
  deploy: { enabled: false, surfaces: [] }
---

# Test Project Context

This is a test project context file.
""")
        
        result = validate_project_context(context_file)
        
        assert result["project"]["name"] == "test-project"
        assert result["project"]["bundle_id"] == "com.example.test"
        assert result["stack"]["language"] == "Python"
        assert result["deployment"]["surface"] == "server"
        assert len(result["invariants"]) == 2
        assert result["invariants"][0]["id"] == "auth_required"
    
    def test_validate_project_context_minimal_valid(self, tmp_path: Path) -> None:
        """Test validation with minimal required fields only."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "minimal-project"
  description: "Minimal test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "cli"
  rollback_available: false
  forced_update: false
  user_data_recoverable: false

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Minimal context.
""")
        
        result = validate_project_context(context_file)
        assert result["project"]["name"] == "minimal-project"
        assert "bundle_id" not in result["project"]
        assert result["invariants"] == []
    
    def test_validate_project_context_missing_required_fields(self, tmp_path: Path) -> None:
        """Test validation fails when required fields are missing."""
        # Test missing top-level section first
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
# missing invariants section
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="Missing required sections: invariants"):
            validate_project_context(context_file)
    
    def test_validate_project_context_missing_project_fields(self, tmp_path: Path) -> None:
        """Test validation fails when required project fields are missing."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  # missing description

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="project section missing required fields: description"):
            validate_project_context(context_file)
    
    def test_validate_project_context_missing_top_level_sections(self, tmp_path: Path) -> None:
        """Test validation fails when top-level sections are missing."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"
# Missing stack, deployment, invariants, reviewers
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="Missing required sections: stack, deployment, invariants, reviewers"):
            validate_project_context(context_file)
    
    def test_validate_project_context_invalid_yaml(self, tmp_path: Path) -> None:
        """Test validation fails with invalid YAML."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"
  invalid_yaml: {
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="Invalid YAML in frontmatter"):
            validate_project_context(context_file)
    
    def test_validate_project_context_no_frontmatter(self, tmp_path: Path) -> None:
        """Test validation fails when no YAML frontmatter is found."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("# Project Context\n\nNo frontmatter here.")
        
        with pytest.raises(ProjectContextError, match="No YAML frontmatter found"):
            validate_project_context(context_file)
    
    def test_validate_project_context_unknown_top_level_sections(self, tmp_path: Path) -> None:
        """Test validation fails when unknown top-level sections are present."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }

unknown_section: "not allowed"
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="Unknown sections not allowed: unknown_section"):
            validate_project_context(context_file)
    
    def test_validate_project_context_unknown_project_fields(self, tmp_path: Path) -> None:
        """Test validation fails when unknown project fields are present."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"
  unknown_field: "not allowed"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="project section has unknown fields: unknown_field"):
            validate_project_context(context_file)
    
    def test_validate_project_context_file_not_found(self, tmp_path: Path) -> None:
        """Test validation fails when file doesn't exist."""
        non_existent = tmp_path / "does_not_exist.md"
        
        with pytest.raises(ProjectContextError, match="Project context file not found"):
            validate_project_context(non_existent)
    
    def test_validate_project_context_invalid_surface_enum(self, tmp_path: Path) -> None:
        """Test validation fails with invalid deployment surface."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "invalid_surface"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="deployment.surface must be one of"):
            validate_project_context(context_file)
    
    def test_validate_project_context_invalid_severity_enum(self, tmp_path: Path) -> None:
        """Test validation fails with invalid invariant severity."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants:
  - id: "test_invariant"
    rule: "Test rule"
    severity: "invalid_severity"

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="invariant 0 severity must be one of"):
            validate_project_context(context_file)
    
    def test_validate_project_context_duplicate_invariant_ids(self, tmp_path: Path) -> None:
        """Test validation fails with duplicate invariant IDs."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants:
  - id: "duplicate_id"
    rule: "First rule"
    severity: "correctness"
  - id: "duplicate_id"
    rule: "Second rule"
    severity: "performance"

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="duplicate invariant id: duplicate_id"):
            validate_project_context(context_file)
    
    def test_validate_project_context_invalid_boolean_fields(self, tmp_path: Path) -> None:
        """Test validation fails when boolean fields are not booleans."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: "yes"  # should be boolean
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="deployment.rollback_available must be a boolean"):
            validate_project_context(context_file)
    
    def test_validate_project_context_invalid_model_class(self, tmp_path: Path) -> None:
        """Test validation fails with invalid reviewer model class."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: invalid_class }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="reviewers.engineer.model_class must be one of"):
            validate_project_context(context_file)
    
    def test_validate_project_context_deploy_reviewer_valid(self, tmp_path: Path) -> None:
        """Test validation passes for deploy reviewer with surfaces field."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
  deploy: { enabled: true, surfaces: ["docker", "kubernetes"] }
---

Test.
""")
        
        result = validate_project_context(context_file)
        assert result["reviewers"]["deploy"]["enabled"] is True
        assert result["reviewers"]["deploy"]["surfaces"] == ["docker", "kubernetes"]
    
    def test_validate_project_context_empty_strings_rejected(self, tmp_path: Path) -> None:
        """Test validation fails when required string fields are empty."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: ""  # empty string
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="project.name must be a non-empty string"):
            validate_project_context(context_file)
    
    def test_validate_project_context_invalid_list_types(self, tmp_path: Path) -> None:
        """Test validation fails when list fields contain wrong types."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"
  primary_files:
    high_blast_radius: [123, 456]  # should be strings

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="stack.primary_files.high_blast_radius must be a list of strings"):
            validate_project_context(context_file)
    
    def test_validate_project_context_non_dict_frontmatter(self, tmp_path: Path) -> None:
        """Test validation fails when YAML frontmatter is not a dictionary."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
- this
- is
- a
- list
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="YAML frontmatter must be a mapping/dictionary"):
            validate_project_context(context_file)
    
    def test_validate_project_context_negative_production_count(self, tmp_path: Path) -> None:
        """Test validation fails with negative production record count."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true
  production_record_count: -100

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="deployment.production_record_count must be a non-negative integer"):
            validate_project_context(context_file)
    
    def test_validate_project_context_multiple_unknown_top_level_sections(self, tmp_path: Path) -> None:
        """Test validation fails with multiple unknown top-level sections."""
        context_file = tmp_path / "project_context.md"
        context_file.write_text("""---
project:
  name: "test-project"
  description: "Test project"

stack:
  language: "Python"
  framework: "FastAPI"

deployment:
  surface: "server"
  rollback_available: true
  forced_update: false
  user_data_recoverable: true

invariants: []

reviewers:
  engineer: { enabled: true, model_class: code_review }
  architect: { enabled: true, model_class: structural_review }
  sre: { enabled: true, model_class: adversarial_review }

unknown_section: "not allowed"
another_unknown: 123
---

Test.
""")
        
        with pytest.raises(ProjectContextError, match="Unknown sections not allowed: another_unknown, unknown_section"):
            validate_project_context(context_file)


class TestProjectContextError:
    """Tests for ProjectContextError exception."""

    def test_project_context_error_inheritance(self) -> None:
        """Test that ProjectContextError inherits from Exception."""
        error = ProjectContextError("test message")
        assert isinstance(error, Exception)
        assert str(error) == "test message"


class TestValidatorEdgeCases:
    """Additional edge-case tests to cover missing validator branches."""

    VALID_CONTENT = """---
project:
  name: Test
  description: A test project
stack:
  language: Python
  framework: FastAPI
  database: PostgreSQL
  primary_files:
    high_blast_radius:
      - app/main.py
    generated:
      - app/schema_gen.py
deployment:
  surface: server
  rollback_available: true
  forced_update: false
  user_data_recoverable: true
  stores:
    - pypi
  production_record_count: 1000
invariants:
  - id: no_delete_without_confirm
    rule: Never delete without user confirmation
    severity: data_loss
reviewers:
  engineer:
    enabled: true
    model_class: code_review
  architect:
    enabled: true
    model_class: structural_review
  sre:
    enabled: true
    model_class: adversarial_review
  deploy:
    enabled: true
    surfaces:
      - server
sharp_edges:
  - location: app/main.py
    issue: Race condition on startup
    fix: Use startup lock
structural_decisions:
  - decision: Monorepo layout
    rationale: Simplifies cross-module imports
becoming:
  - Migrate to async handlers
---
Content here.
"""

    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "project_context.md"
        p.write_text(content)
        return p

    def test_file_read_os_error(self, tmp_path: Path) -> None:
        p = tmp_path / "project_context.md"
        p.write_text("placeholder")
        p.chmod(0o000)
        try:
            with pytest.raises(ProjectContextError, match="Failed to read"):
                validate_project_context(p)
        finally:
            p.chmod(0o644)

    def test_project_section_not_dict(self, tmp_path: Path) -> None:
        content = self.VALID_CONTENT.replace("project:\n  name: Test\n  description: A test project", "project: not_a_dict")
        with pytest.raises(ProjectContextError, match="project section must be a mapping"):
            validate_project_context(self._write(tmp_path, content))

    def test_project_missing_required_fields(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace("  name: Test\n  description: A test project", "  name: Test")
        with pytest.raises(ProjectContextError, match="project section missing required fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_project_unknown_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace("  name: Test", "  name: Test\n  unknown_field: x")
        with pytest.raises(ProjectContextError, match="project section has unknown fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_stack_section_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "stack:\n  language: Python\n  framework: FastAPI\n  database: PostgreSQL\n  primary_files:\n    high_blast_radius:\n      - app/main.py\n    generated:\n      - app/schema_gen.py",
            "stack: scalar"
        )
        with pytest.raises(ProjectContextError, match="stack section must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_stack_unknown_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace("  language: Python", "  language: Python\n  extra_key: bad")
        with pytest.raises(ProjectContextError, match="stack section has unknown fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_stack_database_empty_string(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace("  database: PostgreSQL", "  database: ''")
        with pytest.raises(ProjectContextError, match="stack.database must be a non-empty string"):
            validate_project_context(self._write(tmp_path, bad))

    def test_primary_files_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  primary_files:\n    high_blast_radius:\n      - app/main.py\n    generated:\n      - app/schema_gen.py",
            "  primary_files: scalar"
        )
        with pytest.raises(ProjectContextError, match="stack.primary_files must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_primary_files_unknown_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  primary_files:\n    high_blast_radius:\n      - app/main.py\n    generated:\n      - app/schema_gen.py",
            "  primary_files:\n    high_blast_radius:\n      - app/main.py\n    mystery: oops"
        )
        with pytest.raises(ProjectContextError, match="stack.primary_files has unknown fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_primary_files_not_list(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  primary_files:\n    high_blast_radius:\n      - app/main.py\n    generated:\n      - app/schema_gen.py",
            "  primary_files:\n    high_blast_radius: scalar"
        )
        with pytest.raises(ProjectContextError, match="must be a list"):
            validate_project_context(self._write(tmp_path, bad))

    def test_primary_files_non_string_items(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  primary_files:\n    high_blast_radius:\n      - app/main.py\n    generated:\n      - app/schema_gen.py",
            "  primary_files:\n    high_blast_radius:\n      - 42"
        )
        with pytest.raises(ProjectContextError, match="must be a list of strings"):
            validate_project_context(self._write(tmp_path, bad))

    def test_deployment_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "deployment:\n  surface: server\n  rollback_available: true\n  forced_update: false\n  user_data_recoverable: true\n  stores:\n    - pypi\n  production_record_count: 1000",
            "deployment: scalar"
        )
        with pytest.raises(ProjectContextError, match="deployment section must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_deployment_stores_not_list(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace("  stores:\n    - pypi", "  stores: scalar")
        with pytest.raises(ProjectContextError, match="deployment.stores must be a list"):
            validate_project_context(self._write(tmp_path, bad))

    def test_deployment_stores_non_string_items(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace("  stores:\n    - pypi", "  stores:\n    - 99")
        with pytest.raises(ProjectContextError, match="deployment.stores must be a list of strings"):
            validate_project_context(self._write(tmp_path, bad))

    def test_invariants_not_list(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "invariants:\n  - id: no_delete_without_confirm\n    rule: Never delete without user confirmation\n    severity: data_loss",
            "invariants: scalar"
        )
        with pytest.raises(ProjectContextError, match="invariants section must be a list"):
            validate_project_context(self._write(tmp_path, bad))

    def test_invariant_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "invariants:\n  - id: no_delete_without_confirm\n    rule: Never delete without user confirmation\n    severity: data_loss",
            "invariants:\n  - just_a_string"
        )
        with pytest.raises(ProjectContextError, match="invariant 0 must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_invariant_unknown_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  - id: no_delete_without_confirm\n    rule: Never delete without user confirmation\n    severity: data_loss",
            "  - id: x\n    rule: A rule\n    severity: data_loss\n    extra: oops"
        )
        with pytest.raises(ProjectContextError, match="invariant 0 has unknown fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_invariant_empty_id(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  - id: no_delete_without_confirm\n    rule: Never delete without user confirmation\n    severity: data_loss",
            "  - id: ''\n    rule: A rule\n    severity: data_loss"
        )
        with pytest.raises(ProjectContextError, match="invariant 0 id must be a non-empty string"):
            validate_project_context(self._write(tmp_path, bad))

    def test_reviewers_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "reviewers:\n  engineer:\n    enabled: true\n    model_class: code_review\n  architect:\n    enabled: true\n    model_class: structural_review\n  sre:\n    enabled: true\n    model_class: adversarial_review\n  deploy:\n    enabled: true\n    surfaces:\n      - server",
            "reviewers: scalar"
        )
        with pytest.raises(ProjectContextError, match="reviewers section must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_reviewer_config_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  engineer:\n    enabled: true\n    model_class: code_review",
            "  engineer: scalar"
        )
        with pytest.raises(ProjectContextError, match="reviewers.engineer must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_reviewer_unknown_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  engineer:\n    enabled: true\n    model_class: code_review",
            "  engineer:\n    enabled: true\n    model_class: code_review\n    ghost: field"
        )
        with pytest.raises(ProjectContextError, match="reviewers.engineer has unknown fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_reviewer_enabled_not_bool(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  engineer:\n    enabled: true\n    model_class: code_review",
            "  engineer:\n    enabled: yes_please\n    model_class: code_review"
        )
        with pytest.raises(ProjectContextError, match="reviewers.engineer.enabled must be a boolean"):
            validate_project_context(self._write(tmp_path, bad))

    def test_deploy_reviewer_surfaces_not_list(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  deploy:\n    enabled: true\n    surfaces:\n      - server",
            "  deploy:\n    enabled: true\n    surfaces: scalar"
        )
        with pytest.raises(ProjectContextError, match="reviewers.deploy.surfaces must be a list"):
            validate_project_context(self._write(tmp_path, bad))

    def test_deploy_reviewer_surfaces_non_string(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  deploy:\n    enabled: true\n    surfaces:\n      - server",
            "  deploy:\n    enabled: true\n    surfaces:\n      - 99"
        )
        with pytest.raises(ProjectContextError, match="reviewers.deploy.surfaces must be a list of strings"):
            validate_project_context(self._write(tmp_path, bad))

    def test_sharp_edges_not_list(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "sharp_edges:\n  - location: app/main.py\n    issue: Race condition on startup\n    fix: Use startup lock",
            "sharp_edges: scalar"
        )
        with pytest.raises(ProjectContextError, match="sharp_edges section must be a list"):
            validate_project_context(self._write(tmp_path, bad))

    def test_sharp_edge_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "sharp_edges:\n  - location: app/main.py\n    issue: Race condition on startup\n    fix: Use startup lock",
            "sharp_edges:\n  - just_a_string"
        )
        with pytest.raises(ProjectContextError, match="sharp_edge 0 must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_sharp_edge_unknown_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  - location: app/main.py\n    issue: Race condition on startup\n    fix: Use startup lock",
            "  - location: app/main.py\n    issue: Race condition\n    fix: Use lock\n    extra: oops"
        )
        with pytest.raises(ProjectContextError, match="sharp_edge 0 has unknown fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_sharp_edge_empty_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  - location: app/main.py\n    issue: Race condition on startup\n    fix: Use startup lock",
            "  - location: ''\n    issue: Race condition\n    fix: Use lock"
        )
        with pytest.raises(ProjectContextError, match="sharp_edge 0 location must be a non-empty string"):
            validate_project_context(self._write(tmp_path, bad))

    def test_structural_decisions_not_list(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "structural_decisions:\n  - decision: Monorepo layout\n    rationale: Simplifies cross-module imports",
            "structural_decisions: scalar"
        )
        with pytest.raises(ProjectContextError, match="structural_decisions section must be a list"):
            validate_project_context(self._write(tmp_path, bad))

    def test_structural_decision_not_dict(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "structural_decisions:\n  - decision: Monorepo layout\n    rationale: Simplifies cross-module imports",
            "structural_decisions:\n  - just_a_string"
        )
        with pytest.raises(ProjectContextError, match="structural_decision 0 must be a mapping"):
            validate_project_context(self._write(tmp_path, bad))

    def test_structural_decision_unknown_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  - decision: Monorepo layout\n    rationale: Simplifies cross-module imports",
            "  - decision: Monorepo layout\n    rationale: Simplifies imports\n    extra: oops"
        )
        with pytest.raises(ProjectContextError, match="structural_decision 0 has unknown fields"):
            validate_project_context(self._write(tmp_path, bad))

    def test_structural_decision_empty_field(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "  - decision: Monorepo layout\n    rationale: Simplifies cross-module imports",
            "  - decision: ''\n    rationale: Something"
        )
        with pytest.raises(ProjectContextError, match="structural_decision 0 decision must be a non-empty string"):
            validate_project_context(self._write(tmp_path, bad))

    def test_becoming_not_list(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "becoming:\n  - Migrate to async handlers",
            "becoming: scalar"
        )
        with pytest.raises(ProjectContextError, match="becoming section must be a list"):
            validate_project_context(self._write(tmp_path, bad))

    def test_becoming_empty_string_item(self, tmp_path: Path) -> None:
        bad = self.VALID_CONTENT.replace(
            "becoming:\n  - Migrate to async handlers",
            "becoming:\n  - ''"
        )
        with pytest.raises(ProjectContextError, match="becoming item 0 must be a non-empty string"):
            validate_project_context(self._write(tmp_path, bad))

    def test_full_valid_schema_with_all_optional_sections(self, tmp_path: Path) -> None:
        result = validate_project_context(self._write(tmp_path, self.VALID_CONTENT))
        assert result["project"]["name"] == "Test"
        assert result["deployment"]["surface"] == "server"
        assert len(result["invariants"]) == 1
        assert result["invariants"][0]["id"] == "no_delete_without_confirm"