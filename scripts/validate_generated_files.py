"""Validation for generated file drift detection.

This module provides validation to ensure that generated agent files in 
.factory/agents/ match their source templates plus context. It detects 
manual editing of generated files and template version drift.
"""

import re
from pathlib import Path
from typing import Any

from renderer.compose import _create_generation_header, _extract_template_version
from renderer.validators import validate_project_context

__all__ = ["GeneratedFileValidator", "ValidationError"]


class ValidationError(Exception):
    """Raised when generated file validation fails."""


class GeneratedFileValidator:
    """Validates that generated agent files match their templates + context."""

    def __init__(self, templates_dir: Path) -> None:
        """Initialize validator with templates directory.
        
        Args:
            templates_dir: Path to directory containing template files
            
        Raises:
            ValidationError: If templates directory doesn't exist
        """
        if not templates_dir.exists():
            raise ValidationError(f"Templates directory not found: {templates_dir}")
        
        self.templates_dir = templates_dir

    def validate_agents_directory(self, factory_dir: Path) -> list[str]:
        """Validate all generated agent files in .factory/agents/.
        
        Args:
            factory_dir: Path to .factory directory
            
        Returns:
            List of validation error messages (empty if all valid)
            
        Raises:
            ValidationError: If validation cannot be performed
        """
        errors: list[str] = []
        
        # Check if factory directory exists
        if not factory_dir.exists():
            return [f"Factory directory not found: {factory_dir}"]
            
        # Check if agents directory exists
        agents_dir = factory_dir / "agents"
        if not agents_dir.exists():
            return [f"Agents directory not found: {agents_dir}"]
        
        # Check if project_context.md exists
        project_context_path = factory_dir / "project_context.md"
        if not project_context_path.exists():
            errors.append(f"Project context file not found: {project_context_path}")
            return errors
            
        # Validate project context and get data
        try:
            context_data = validate_project_context(project_context_path)
        except Exception as e:
            errors.append(f"Invalid project context: {e}")
            return errors
            
        # Find all agent files in agents directory
        agent_files = list(agents_dir.glob("*.md"))
        if not agent_files:
            # No agent files to validate - this is valid (no reviewers enabled)
            return errors
            
        # Validate each agent file
        for agent_file in agent_files:
            file_errors = self._validate_agent_file(agent_file, context_data)
            errors.extend(file_errors)
            
        return errors
    
    def _validate_agent_file(self, agent_file: Path, context_data: dict[str, Any]) -> list[str]:
        """Validate a single agent file.
        
        Args:
            agent_file: Path to agent file to validate
            context_data: Validated project context data
            
        Returns:
            List of validation errors for this file
        """
        errors: list[str] = []
        
        try:
            current_content = agent_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return [f"Failed to read {agent_file.name}: {e}"]
            
        # Check for generation header
        if not self._has_generation_header(current_content):
            errors.append(f"{agent_file.name}: Missing generation header")
            return errors
            
        # Extract template info from header
        try:
            template_name, template_version = self._extract_header_info(current_content)
        except ValidationError as e:
            errors.append(f"{agent_file.name}: {e}")
            return errors
            
        # Find corresponding template
        template_path = self.templates_dir / template_name
        if not template_path.exists():
            errors.append(f"{agent_file.name}: Template file not found: {template_name}")
            return errors
            
        # Check template version
        try:
            template_content = template_path.read_text(encoding="utf-8")
            current_template_version = _extract_template_version(template_content)
            
            if current_template_version != template_version:
                errors.append(
                    f"{agent_file.name}: Template version mismatch - "
                    f"file has v{template_version}, template has v{current_template_version}"
                )
                # Don't check content if version mismatch - the content will be wrong anyway
                return errors
        except Exception as e:
            errors.append(f"{agent_file.name}: Failed to check template version: {e}")
            return errors
            
        # Generate expected content and compare
        try:
            expected_content = self._generate_expected_content(
                template_path, context_data, agent_file.stem
            )
            
            if current_content != expected_content:
                errors.append(
                    f"{agent_file.name}: Content drift detected - "
                    "file content doesn't match template + context"
                )
        except Exception as e:
            errors.append(f"{agent_file.name}: Failed to generate expected content: {e}")
            
        return errors
    
    def _has_generation_header(self, content: str) -> bool:
        """Check if content has the expected generation header.
        
        Args:
            content: File content to check
            
        Returns:
            True if generation header is present
        """
        return content.startswith("<!-- GENERATED FILE — DO NOT EDIT -->")
    
    def _extract_header_info(self, content: str) -> tuple[str, str]:
        """Extract template name and version from generation header.
        
        Args:
            content: File content
            
        Returns:
            Tuple of (template_name, template_version)
            
        Raises:
            ValidationError: If header info cannot be extracted
        """
        lines = content.split('\n')
        if len(lines) < 2:
            raise ValidationError("Invalid generation header format")
            
        source_line = lines[1]
        
        # Parse source line: <!-- Source: template.md vX.Y.Z + project_context.md -->
        source_match = re.match(
            r'<!-- Source: ([^\s]+) v([^\s]+) \+ project_context\.md -->',
            source_line
        )
        
        if not source_match:
            raise ValidationError("Could not parse template info from header")
            
        template_name = source_match.group(1)
        template_version = source_match.group(2)
        
        return template_name, template_version
    
    def _generate_expected_content(
        self, 
        template_path: Path, 
        context_data: dict[str, Any],
        reviewer_name: str
    ) -> str:
        """Generate expected content for comparison.
        
        Args:
            template_path: Path to template file
            context_data: Project context data
            reviewer_name: Name of reviewer (engineer, architect, etc.)
            
        Returns:
            Expected file content
            
        Raises:
            Exception: If content generation fails
        """
        from renderer.compose import compose_agent
        from tempfile import NamedTemporaryFile
        import os
        
        # Create a temporary file to render into
        with NamedTemporaryFile(mode='w+', suffix='.md', delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            
        try:
            # Add reviewer-specific variables to context (matching render.py logic)
            enhanced_context = {
                **context_data,
                "reviewer_role": reviewer_name.title(),
                "project_context": context_data["project"]["name"],
            }
            
            # Render the template
            compose_agent(template_path, enhanced_context, temp_path)
            
            # Read back the generated content
            return temp_path.read_text(encoding="utf-8")
            
        finally:
            # Clean up temp file
            if temp_path.exists():
                os.unlink(temp_path)


def main() -> int:
    """CLI entry point for validation.
    
    Returns:
        Exit code: 0 for success, 1 for validation errors
    """
    import sys
    
    if len(sys.argv) != 2:
        print("Usage: python validate_generated_files.py <factory_dir>", file=sys.stderr)
        return 1
        
    factory_dir = Path(sys.argv[1])
    templates_dir = Path(__file__).parent.parent / "templates"
    
    try:
        validator = GeneratedFileValidator(templates_dir)
        errors = validator.validate_agents_directory(factory_dir)
        
        if errors:
            print("Generated file validation errors found:", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
            return 1
        else:
            print("All generated files are valid")
            return 0
            
    except ValidationError as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    exit(main())