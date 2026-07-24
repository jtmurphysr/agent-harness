"""Tests for generated file validation."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent

from scripts.validate_generated_files import GeneratedFileValidator, ValidationError


class TestGeneratedFileValidator:
    """Test cases for GeneratedFileValidator class."""

    def test_init_success(self, tmp_path: Path) -> None:
        """Test successful validator initialization."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        assert validator.templates_dir == templates_dir

    def test_init_templates_dir_not_found(self, tmp_path: Path) -> None:
        """Test initialization fails when templates directory doesn't exist."""
        templates_dir = tmp_path / "nonexistent"
        
        with pytest.raises(ValidationError, match="Templates directory not found"):
            GeneratedFileValidator(templates_dir)

    def test_validate_agents_directory_clean(self, tmp_path: Path) -> None:
        """Test validation passes for properly generated files."""
        # Set up templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        # Create shared partials directory
        shared_dir = templates_dir / "_shared"
        shared_dir.mkdir()
        (shared_dir / "output_contract.partial.md").write_text("Output contract content")
        
        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text(dedent("""
            ---
            version: "1.0.0"
            propagation: opt_in
            ---
            
            You are the {{ reviewer_role }} reviewer for **{{ project.name }}**.
            
            ## Project Context
            Stack: {{ stack.language }}
        """).strip())
        
        # Set up factory directory
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with properly generated file
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_content = dedent("""
            <!-- GENERATED FILE — DO NOT EDIT -->
            <!-- Source: engineer.template.md v1.0.0 + project_context.md -->
            <!-- Regenerate with: harness render -->
            
            ---
            version: "1.0.0"
            propagation: opt_in
            ---
            
            You are the Engineer reviewer for **TestProject**.
            
            ## Project Context
            Stack: Python
        """).strip()
        engineer_file.write_text(engineer_content)
        
        # Test validation
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert errors == []

    def test_validate_agents_directory_drift_detected(self, tmp_path: Path) -> None:
        """Test validation detects content drift."""
        # Set up templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        # Create shared partials directory
        shared_dir = templates_dir / "_shared"
        shared_dir.mkdir()
        (shared_dir / "output_contract.partial.md").write_text("Output contract content")
        
        # Create engineer template
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text(dedent("""
            ---
            version: "1.0.0"
            ---
            
            You are the {{ reviewer_role }} reviewer for **{{ project.name }}**.
        """).strip())
        
        # Set up factory directory
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with modified file
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_content = dedent("""
            <!-- GENERATED FILE — DO NOT EDIT -->
            <!-- Source: engineer.template.md v1.0.0 + project_context.md -->
            <!-- Regenerate with: harness render -->
            
            You are the Engineer reviewer for **TestProject**.
            
            MANUALLY EDITED CONTENT THAT SHOULDN'T BE HERE
        """).strip()
        engineer_file.write_text(engineer_content)
        
        # Test validation
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Content drift detected" in errors[0]
        assert "engineer.md" in errors[0]

    def test_validate_agents_directory_missing_generation_header(self, tmp_path: Path) -> None:
        """Test validation detects missing generation headers."""
        # Set up templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        # Set up factory directory
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with file missing header
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_file.write_text("This file has no generation header")
        
        # Test validation
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Missing generation header" in errors[0]
        assert "engineer.md" in errors[0]

    def test_validate_agents_directory_template_version_mismatch(self, tmp_path: Path) -> None:
        """Test validation detects template version mismatches."""
        # Set up templates directory
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        # Create engineer template with newer version
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text(dedent("""
            ---
            version: "1.1.0"
            propagation: opt_in
            ---
            
            You are the {{ reviewer_role }} reviewer for **{{ project.name }}**.
            
            ## Project Context
            Stack: {{ stack.language }}
        """).strip())
        
        # Set up factory directory
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with file referencing older template version
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_content = dedent("""
            <!-- GENERATED FILE — DO NOT EDIT -->
            <!-- Source: engineer.template.md v1.0.0 + project_context.md -->
            <!-- Regenerate with: harness render -->
            
            Old content
        """).strip()
        engineer_file.write_text(engineer_content)
        
        # Test validation
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Template version mismatch" in errors[0]
        assert "file has v1.0.0, template has v1.1.0" in errors[0]

    def test_validate_agents_directory_factory_not_found(self, tmp_path: Path) -> None:
        """Test validation when factory directory doesn't exist."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        factory_dir = tmp_path / "nonexistent"
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Factory directory not found" in errors[0]

    def test_validate_agents_directory_agents_not_found(self, tmp_path: Path) -> None:
        """Test validation when agents directory doesn't exist."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Agents directory not found" in errors[0]

    def test_validate_agents_directory_no_project_context(self, tmp_path: Path) -> None:
        """Test validation when project_context.md is missing."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Project context file not found" in errors[0]

    def test_validate_agents_directory_no_agents(self, tmp_path: Path) -> None:
        """Test validation when no agent files exist (valid case)."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: false
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        # No errors - it's valid to have no agents if no reviewers are enabled
        assert errors == []

    def test_validate_agents_directory_invalid_project_context(self, tmp_path: Path) -> None:
        """Test validation when project_context.md is invalid."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create invalid project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text("Invalid YAML content")
        
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Invalid project context" in errors[0]

    def test_validate_agents_directory_template_not_found(self, tmp_path: Path) -> None:
        """Test validation when referenced template doesn't exist."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with file referencing nonexistent template
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_content = dedent("""
            <!-- GENERATED FILE — DO NOT EDIT -->
            <!-- Source: nonexistent.template.md v1.0.0 + project_context.md -->
            <!-- Regenerate with: harness render -->
            
            Content
        """).strip()
        engineer_file.write_text(engineer_content)
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Template file not found: nonexistent.template.md" in errors[0]

    def test_has_generation_header_positive(self, tmp_path: Path) -> None:
        """Test _has_generation_header returns True for valid header."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        
        content = "<!-- GENERATED FILE — DO NOT EDIT -->\nMore content"
        assert validator._has_generation_header(content) is True

    def test_has_generation_header_negative(self, tmp_path: Path) -> None:
        """Test _has_generation_header returns False for missing header."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        
        content = "Some regular content"
        assert validator._has_generation_header(content) is False

    def test_extract_header_info_success(self, tmp_path: Path) -> None:
        """Test _extract_header_info successfully parses header."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        
        content = dedent("""
            <!-- GENERATED FILE — DO NOT EDIT -->
            <!-- Source: engineer.template.md v1.2.3 + project_context.md -->
            <!-- Regenerate with: harness render -->
        """).strip()
        
        template_name, version = validator._extract_header_info(content)
        assert template_name == "engineer.template.md"
        assert version == "1.2.3"

    def test_extract_header_info_invalid_format(self, tmp_path: Path) -> None:
        """Test _extract_header_info raises error for invalid format."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        
        content = "<!-- GENERATED FILE — DO NOT EDIT -->\nInvalid header format"
        
        with pytest.raises(ValidationError, match="Could not parse template info"):
            validator._extract_header_info(content)

    def test_extract_header_info_too_short(self, tmp_path: Path) -> None:
        """Test _extract_header_info raises error for too short content."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        validator = GeneratedFileValidator(templates_dir)
        
        content = "<!-- GENERATED FILE — DO NOT EDIT -->"
        
        with pytest.raises(ValidationError, match="Invalid generation header format"):
            validator._extract_header_info(content)

    def test_cli_main_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CLI main function with successful validation."""
        import sys
        from scripts.validate_generated_files import main
        
        # Set up valid factory directory structure
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: false
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create empty agents directory (valid - no reviewers enabled)
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        # Mock sys.argv
        monkeypatch.setattr(sys, "argv", ["validate_generated_files.py", str(factory_dir)])
        
        # Call main function
        result = main()
        assert result == 0

    def test_cli_main_validation_errors(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CLI main function with validation errors."""
        import sys
        from scripts.validate_generated_files import main
        
        # Set up factory directory with invalid file
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with file missing header
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_file.write_text("This file has no generation header")
        
        # Mock sys.argv
        monkeypatch.setattr(sys, "argv", ["validate_generated_files.py", str(factory_dir)])
        
        # Call main function
        result = main()
        assert result == 1

    def test_cli_main_wrong_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CLI main function with wrong number of arguments."""
        import sys
        from scripts.validate_generated_files import main
        
        # Mock sys.argv with wrong number of args
        monkeypatch.setattr(sys, "argv", ["validate_generated_files.py"])
        
        # Call main function
        result = main()
        assert result == 1

    def test_cli_main_validation_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CLI main function with ValidationError exception."""
        import sys
        from scripts.validate_generated_files import main
        
        # Use nonexistent templates directory to trigger ValidationError
        factory_dir = tmp_path / ".factory"
        
        # Mock sys.argv
        monkeypatch.setattr(sys, "argv", ["validate_generated_files.py", str(factory_dir)])
        
        # Call main function
        result = main()
        assert result == 1

    def test_generate_expected_content_with_compose_error(self, tmp_path: Path) -> None:
        """Test _generate_expected_content handles compose errors."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        # Create invalid template that will cause compose error
        template_path = templates_dir / "bad_template.md"
        template_path.write_text("Invalid template without frontmatter")
        
        validator = GeneratedFileValidator(templates_dir)
        context_data = {"project": {"name": "Test"}}
        
        # Should raise an exception due to invalid template
        with pytest.raises(Exception):
            validator._generate_expected_content(template_path, context_data, "test")

    def test_file_read_errors(self, tmp_path: Path) -> None:
        """Test validation handles file read errors."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        # Create a directory instead of a file (will cause read error)
        bad_file = agents_dir / "engineer.md"
        bad_file.mkdir()  # This creates a directory, not a file
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Failed to read engineer.md" in errors[0]

    def test_cli_main_unexpected_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test CLI main function with unexpected exception."""
        import sys
        from scripts.validate_generated_files import main, GeneratedFileValidator
        
        # Mock an unexpected exception in validator initialization
        def mock_init(self, templates_dir):
            raise RuntimeError("Unexpected error")
        
        monkeypatch.setattr(GeneratedFileValidator, "__init__", mock_init)
        monkeypatch.setattr(sys, "argv", ["validate_generated_files.py", str(tmp_path)])
        
        # Call main function
        result = main()
        assert result == 1

    def test_template_version_check_error(self, tmp_path: Path) -> None:
        """Test error handling when template version check fails."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        # Create invalid template that will cause version extraction to fail
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text("No frontmatter at all")
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with file referencing the template
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_content = dedent("""
            <!-- GENERATED FILE — DO NOT EDIT -->
            <!-- Source: engineer.template.md v1.0.0 + project_context.md -->
            <!-- Regenerate with: harness render -->
            
            Content
        """).strip()
        engineer_file.write_text(engineer_content)
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Failed to check template version" in errors[0]

    def test_content_generation_error(self, tmp_path: Path) -> None:
        """Test error handling when content generation fails."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        
        # Create template that will cause content generation to fail
        engineer_template = templates_dir / "engineer.template.md"
        engineer_template.write_text(dedent("""
            ---
            version: "1.0.0"
            propagation: opt_in
            ---
            
            Template with missing variable: {{ missing_variable }}
        """).strip())
        
        factory_dir = tmp_path / ".factory"
        factory_dir.mkdir()
        
        # Create project context (minimal to trigger the missing variable error)
        project_context = factory_dir / "project_context.md"
        project_context.write_text(dedent("""
            ---
            project:
              name: TestProject
              description: A test project
              
            stack:
              language: Python
              framework: FastAPI
              
            deployment:
              surface: server
              rollback_available: true
              forced_update: false
              user_data_recoverable: true
              
            invariants: []
              
            reviewers:
              engineer:
                enabled: true
                model_class: code_review
              architect:
                enabled: false
                model_class: structural_review
              sre:
                enabled: false
                model_class: adversarial_review
            ---
        """).strip())
        
        # Create agents directory with file referencing the template
        agents_dir = factory_dir / "agents"
        agents_dir.mkdir()
        
        engineer_file = agents_dir / "engineer.md"
        engineer_content = dedent("""
            <!-- GENERATED FILE — DO NOT EDIT -->
            <!-- Source: engineer.template.md v1.0.0 + project_context.md -->
            <!-- Regenerate with: harness render -->
            
            Content
        """).strip()
        engineer_file.write_text(engineer_content)
        
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        assert len(errors) == 1
        assert "Failed to generate expected content" in errors[0]