"""Schema validation for project_context.md files."""

import re
from pathlib import Path
from typing import Any

import yaml

__all__ = ["ProjectContextError", "validate_project_context"]


class ProjectContextError(Exception):
    """Raised when project_context.md validation fails."""


def validate_project_context(context_path: Path) -> dict[str, Any]:
    """Validate project_context.md schema and return parsed data.

    Args:
        context_path: Path to the project_context.md file

    Returns:
        Parsed YAML frontmatter data

    Raises:
        ProjectContextError: If validation fails
    """
    if not context_path.exists():
        raise ProjectContextError(f"Project context file not found: {context_path}")

    try:
        content = context_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ProjectContextError(f"Failed to read project context file: {e}") from e

    # Extract YAML frontmatter
    frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not frontmatter_match:
        raise ProjectContextError("No YAML frontmatter found in project_context.md")

    frontmatter_text = frontmatter_match.group(1)

    # Parse YAML safely
    try:
        data = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as e:
        raise ProjectContextError(f"Invalid YAML in frontmatter: {e}") from e

    if not isinstance(data, dict):
        raise ProjectContextError("YAML frontmatter must be a mapping/dictionary")

    # Validate required top-level sections
    required_sections = ["project", "stack", "deployment", "invariants", "reviewers"]
    missing_sections = [section for section in required_sections if section not in data]
    if missing_sections:
        raise ProjectContextError(f"Missing required sections: {', '.join(missing_sections)}")

    # Check for unknown top-level fields
    allowed_sections = {
        "project",
        "stack",
        "deployment",
        "invariants",
        "sharp_edges",
        "structural_decisions",
        "becoming",
        "reviewers",
    }
    unknown_sections = set(data.keys()) - allowed_sections
    if unknown_sections:
        raise ProjectContextError(
            f"Unknown sections not allowed: {', '.join(sorted(unknown_sections))}"
        )

    # Validate project section
    _validate_project_section(data["project"])

    # Validate stack section
    _validate_stack_section(data["stack"])

    # Validate deployment section
    _validate_deployment_section(data["deployment"])

    # Validate invariants section
    _validate_invariants_section(data["invariants"])

    # Validate reviewers section
    _validate_reviewers_section(data["reviewers"])

    # Validate optional sections if present
    if "sharp_edges" in data:
        _validate_sharp_edges_section(data["sharp_edges"])

    if "structural_decisions" in data:
        _validate_structural_decisions_section(data["structural_decisions"])

    if "becoming" in data:
        _validate_becoming_section(data["becoming"])

    return data


def _validate_project_section(project: Any) -> None:
    """Validate the project section."""
    if not isinstance(project, dict):
        raise ProjectContextError("project section must be a mapping")

    required_fields = ["name", "description"]
    missing_fields = [field for field in required_fields if field not in project]
    if missing_fields:
        raise ProjectContextError(
            f"project section missing required fields: {', '.join(missing_fields)}"
        )

    allowed_fields = {"name", "bundle_id", "description"}
    unknown_fields = set(project.keys()) - allowed_fields
    if unknown_fields:
        raise ProjectContextError(
            f"project section has unknown fields: {', '.join(sorted(unknown_fields))}"
        )

    if not isinstance(project["name"], str) or not project["name"].strip():
        raise ProjectContextError("project.name must be a non-empty string")

    if not isinstance(project["description"], str) or not project["description"].strip():
        raise ProjectContextError("project.description must be a non-empty string")

    if "bundle_id" in project and (
        not isinstance(project["bundle_id"], str) or not project["bundle_id"].strip()
    ):
        raise ProjectContextError("project.bundle_id must be a non-empty string")


def _validate_stack_section(stack: Any) -> None:
    """Validate the stack section."""
    if not isinstance(stack, dict):
        raise ProjectContextError("stack section must be a mapping")

    required_fields = ["language", "framework"]
    missing_fields = [field for field in required_fields if field not in stack]
    if missing_fields:
        raise ProjectContextError(
            f"stack section missing required fields: {', '.join(missing_fields)}"
        )

    allowed_fields = {"language", "framework", "database", "primary_files"}
    unknown_fields = set(stack.keys()) - allowed_fields
    if unknown_fields:
        raise ProjectContextError(
            f"stack section has unknown fields: {', '.join(sorted(unknown_fields))}"
        )

    if not isinstance(stack["language"], str) or not stack["language"].strip():
        raise ProjectContextError("stack.language must be a non-empty string")

    if not isinstance(stack["framework"], str) or not stack["framework"].strip():
        raise ProjectContextError("stack.framework must be a non-empty string")

    if "database" in stack and (
        not isinstance(stack["database"], str) or not stack["database"].strip()
    ):
        raise ProjectContextError("stack.database must be a non-empty string")

    if "primary_files" in stack:
        _validate_primary_files(stack["primary_files"])


def _validate_primary_files(primary_files: Any) -> None:
    """Validate the primary_files subsection."""
    if not isinstance(primary_files, dict):
        raise ProjectContextError("stack.primary_files must be a mapping")

    allowed_fields = {"high_blast_radius", "generated"}
    unknown_fields = set(primary_files.keys()) - allowed_fields
    if unknown_fields:
        raise ProjectContextError(
            f"stack.primary_files has unknown fields: {', '.join(sorted(unknown_fields))}"
        )

    for field in ["high_blast_radius", "generated"]:
        if field in primary_files:
            value = primary_files[field]
            if not isinstance(value, list):
                raise ProjectContextError(f"stack.primary_files.{field} must be a list")
            if not all(isinstance(item, str) for item in value):
                raise ProjectContextError(f"stack.primary_files.{field} must be a list of strings")


def _validate_deployment_section(deployment: Any) -> None:
    """Validate the deployment section."""
    if not isinstance(deployment, dict):
        raise ProjectContextError("deployment section must be a mapping")

    required_fields = ["surface", "rollback_available", "forced_update", "user_data_recoverable"]
    missing_fields = [field for field in required_fields if field not in deployment]
    if missing_fields:
        raise ProjectContextError(
            f"deployment section missing required fields: {', '.join(missing_fields)}"
        )

    allowed_fields = {
        "surface",
        "stores",
        "rollback_available",
        "forced_update",
        "user_data_recoverable",
        "production_record_count",
    }
    unknown_fields = set(deployment.keys()) - allowed_fields
    if unknown_fields:
        raise ProjectContextError(
            f"deployment section has unknown fields: {', '.join(sorted(unknown_fields))}"
        )

    # Validate surface enum
    valid_surfaces = {"mobile", "server", "cli", "embedded", "library"}
    if deployment["surface"] not in valid_surfaces:
        raise ProjectContextError(
            f"deployment.surface must be one of: {', '.join(sorted(valid_surfaces))}"
        )

    # Validate boolean fields
    for field in ["rollback_available", "forced_update", "user_data_recoverable"]:
        if not isinstance(deployment[field], bool):
            raise ProjectContextError(f"deployment.{field} must be a boolean")

    # Validate optional fields
    if "stores" in deployment:
        stores = deployment["stores"]
        if not isinstance(stores, list):
            raise ProjectContextError("deployment.stores must be a list")
        if not all(isinstance(store, str) for store in stores):
            raise ProjectContextError("deployment.stores must be a list of strings")

    if "production_record_count" in deployment:
        count = deployment["production_record_count"]
        if not isinstance(count, int) or count < 0:
            raise ProjectContextError(
                "deployment.production_record_count must be a non-negative integer"
            )


def _validate_invariants_section(invariants: Any) -> None:
    """Validate the invariants section."""
    if not isinstance(invariants, list):
        raise ProjectContextError("invariants section must be a list")

    seen_ids = set()
    valid_severities = {
        "data_loss",
        "data_consistency",
        "irreversibility",
        "correctness",
        "performance",
    }

    for i, invariant in enumerate(invariants):
        if not isinstance(invariant, dict):
            raise ProjectContextError(f"invariant {i} must be a mapping")

        required_fields = ["id", "rule", "severity"]
        missing_fields = [field for field in required_fields if field not in invariant]
        if missing_fields:
            raise ProjectContextError(
                f"invariant {i} missing required fields: {', '.join(missing_fields)}"
            )

        unknown_fields = set(invariant.keys()) - {"id", "rule", "severity"}
        if unknown_fields:
            raise ProjectContextError(
                f"invariant {i} has unknown fields: {', '.join(sorted(unknown_fields))}"
            )

        invariant_id = invariant["id"]
        if not isinstance(invariant_id, str) or not invariant_id.strip():
            raise ProjectContextError(f"invariant {i} id must be a non-empty string")

        if invariant_id in seen_ids:
            raise ProjectContextError(f"duplicate invariant id: {invariant_id}")
        seen_ids.add(invariant_id)

        if not isinstance(invariant["rule"], str) or not invariant["rule"].strip():
            raise ProjectContextError(f"invariant {i} rule must be a non-empty string")

        if invariant["severity"] not in valid_severities:
            raise ProjectContextError(
                f"invariant {i} severity must be one of: {', '.join(sorted(valid_severities))}"
            )


def _validate_reviewers_section(reviewers: Any) -> None:
    """Validate the reviewers section."""
    if not isinstance(reviewers, dict):
        raise ProjectContextError("reviewers section must be a mapping")

    required_reviewers = ["engineer", "architect", "sre"]
    missing_reviewers = [reviewer for reviewer in required_reviewers if reviewer not in reviewers]
    if missing_reviewers:
        raise ProjectContextError(
            f"reviewers section missing required reviewers: {', '.join(missing_reviewers)}"
        )

    allowed_reviewers = {"engineer", "architect", "sre", "deploy"}
    unknown_reviewers = set(reviewers.keys()) - allowed_reviewers
    if unknown_reviewers:
        raise ProjectContextError(
            f"reviewers section has unknown reviewers: {', '.join(sorted(unknown_reviewers))}"
        )

    valid_model_classes = {"code_review", "structural_review", "adversarial_review"}

    for reviewer_name, config in reviewers.items():
        if not isinstance(config, dict):
            raise ProjectContextError(f"reviewers.{reviewer_name} must be a mapping")

        required_fields = ["enabled", "model_class"]
        if reviewer_name == "deploy":
            required_fields = ["enabled", "surfaces"]

        missing_fields = [field for field in required_fields if field not in config]
        if missing_fields:
            raise ProjectContextError(
                f"reviewers.{reviewer_name} missing required fields: {', '.join(missing_fields)}"
            )

        allowed_fields = {"enabled", "model_class", "surfaces"}
        unknown_fields = set(config.keys()) - allowed_fields
        if unknown_fields:
            raise ProjectContextError(
                f"reviewers.{reviewer_name} has unknown fields: {', '.join(sorted(unknown_fields))}"
            )

        if not isinstance(config["enabled"], bool):
            raise ProjectContextError(f"reviewers.{reviewer_name}.enabled must be a boolean")

        if reviewer_name == "deploy":
            surfaces = config["surfaces"]
            if not isinstance(surfaces, list):
                raise ProjectContextError(f"reviewers.{reviewer_name}.surfaces must be a list")
            if not all(isinstance(surface, str) for surface in surfaces):
                raise ProjectContextError(
                    f"reviewers.{reviewer_name}.surfaces must be a list of strings"
                )
        else:
            model_class = config["model_class"]
            if model_class not in valid_model_classes:
                raise ProjectContextError(
                    f"reviewers.{reviewer_name}.model_class must be one of: {', '.join(sorted(valid_model_classes))}"
                )


def _validate_sharp_edges_section(sharp_edges: Any) -> None:
    """Validate the optional sharp_edges section."""
    if not isinstance(sharp_edges, list):
        raise ProjectContextError("sharp_edges section must be a list")

    for i, edge in enumerate(sharp_edges):
        if not isinstance(edge, dict):
            raise ProjectContextError(f"sharp_edge {i} must be a mapping")

        required_fields = ["location", "issue", "fix"]
        missing_fields = [field for field in required_fields if field not in edge]
        if missing_fields:
            raise ProjectContextError(
                f"sharp_edge {i} missing required fields: {', '.join(missing_fields)}"
            )

        unknown_fields = set(edge.keys()) - {"location", "issue", "fix"}
        if unknown_fields:
            raise ProjectContextError(
                f"sharp_edge {i} has unknown fields: {', '.join(sorted(unknown_fields))}"
            )

        for field in ["location", "issue", "fix"]:
            if not isinstance(edge[field], str) or not edge[field].strip():
                raise ProjectContextError(f"sharp_edge {i} {field} must be a non-empty string")


def _validate_structural_decisions_section(structural_decisions: Any) -> None:
    """Validate the optional structural_decisions section."""
    if not isinstance(structural_decisions, list):
        raise ProjectContextError("structural_decisions section must be a list")

    for i, decision in enumerate(structural_decisions):
        if not isinstance(decision, dict):
            raise ProjectContextError(f"structural_decision {i} must be a mapping")

        required_fields = ["decision", "rationale"]
        missing_fields = [field for field in required_fields if field not in decision]
        if missing_fields:
            raise ProjectContextError(
                f"structural_decision {i} missing required fields: {', '.join(missing_fields)}"
            )

        unknown_fields = set(decision.keys()) - {"decision", "rationale"}
        if unknown_fields:
            raise ProjectContextError(
                f"structural_decision {i} has unknown fields: {', '.join(sorted(unknown_fields))}"
            )

        for field in ["decision", "rationale"]:
            if not isinstance(decision[field], str) or not decision[field].strip():
                raise ProjectContextError(
                    f"structural_decision {i} {field} must be a non-empty string"
                )


def _validate_becoming_section(becoming: Any) -> None:
    """Validate the optional becoming section."""
    if not isinstance(becoming, list):
        raise ProjectContextError("becoming section must be a list")

    for i, item in enumerate(becoming):
        if not isinstance(item, str) or not item.strip():
            raise ProjectContextError(f"becoming item {i} must be a non-empty string")
