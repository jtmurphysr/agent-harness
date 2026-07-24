"""Model class to concrete model resolution for reviewer dispatch."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

__all__ = ["ModelConfig", "ModelResolutionError", "ModelResolver"]


class ModelResolutionError(Exception):
    """Raised when model resolution fails."""

    pass


class ModelConfig(BaseModel):
    """Configuration for a resolved model."""

    model_class: str
    model_name: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)


class ModelResolver:
    """Resolves model classes to concrete model configurations."""

    def __init__(self, model_map_path: Path) -> None:
        """Initialize with path to model map YAML file.

        Args:
            model_map_path: Path to ~/.factory/model_map.yml or similar

        Raises:
            ModelResolutionError: If model map file cannot be read
        """
        self.model_map_path = model_map_path
        self._model_map: dict[str, dict[str, Any]] = {}
        self._load_model_map()

    def _load_model_map(self) -> None:
        """Load model map from YAML file."""
        try:
            if not self.model_map_path.exists():
                # Create default model map if it doesn't exist
                self._create_default_model_map()
                return

            with open(self.model_map_path) as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                raise ModelResolutionError(f"Model map must be a dictionary, got {type(data)}")

            self._model_map = data

        except (OSError, yaml.YAMLError) as e:
            raise ModelResolutionError(
                f"Failed to load model map from {self.model_map_path}: {e}"
            ) from e

    def _create_default_model_map(self) -> None:
        """Create default model map with sensible defaults."""
        default_map = {
            "code_review": {
                "model_name": "claude-3-5-sonnet-20241022",
                "temperature": 0.3,
                "max_tokens": 4096,
            },
            "structural_review": {
                "model_name": "claude-3-5-sonnet-20241022",
                "temperature": 0.5,
                "max_tokens": 4096,
            },
            "adversarial_review": {
                "model_name": "claude-3-5-sonnet-20241022",
                "temperature": 0.7,
                "max_tokens": 4096,
            },
        }

        # Create directory if it doesn't exist
        self.model_map_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(self.model_map_path, "w") as f:
                yaml.safe_dump(default_map, f, default_flow_style=False)
            self._model_map = default_map
        except OSError as e:
            raise ModelResolutionError(
                f"Failed to create default model map at {self.model_map_path}: {e}"
            ) from e

    def resolve_model(
        self, model_class: str, project_overrides: dict[str, Any] | None = None
    ) -> ModelConfig:
        """Resolve a model class to concrete configuration.

        Args:
            model_class: Model class name (e.g. "code_review", "structural_review")
            project_overrides: Project-specific overrides from project_context.md

        Returns:
            ModelConfig with resolved model configuration

        Raises:
            ModelResolutionError: If model class cannot be resolved
        """
        if model_class not in self._model_map:
            raise ModelResolutionError(f"Unknown model class: {model_class}")

        # Start with defaults from model map
        config_dict = self._model_map[model_class].copy()
        config_dict["model_class"] = model_class

        # Apply project-specific overrides if provided
        if project_overrides:
            reviewer_overrides = project_overrides.get("reviewers", {})

            # Find the reviewer that uses this model class
            for _reviewer_name, reviewer_config in reviewer_overrides.items():
                if (
                    isinstance(reviewer_config, dict)
                    and reviewer_config.get("model_class") == model_class
                ):
                    # Apply any explicit overrides
                    if "model_name" in reviewer_config:
                        config_dict["model_name"] = reviewer_config["model_name"]
                    if "temperature" in reviewer_config:
                        config_dict["temperature"] = reviewer_config["temperature"]
                    if "max_tokens" in reviewer_config:
                        config_dict["max_tokens"] = reviewer_config["max_tokens"]
                    break

        try:
            return ModelConfig(**config_dict)
        except Exception as e:
            raise ModelResolutionError(f"Invalid model configuration for {model_class}: {e}") from e
