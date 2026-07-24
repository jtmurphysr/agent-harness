"""Tests for reviewers.models module."""

import tempfile
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
import yaml

from reviewers.models import ModelConfig, ModelResolver, ModelResolutionError


class TestModelConfig:
    """Tests for ModelConfig class."""
    
    def test_model_config_valid(self) -> None:
        """Test ModelConfig creation with valid values."""
        config = ModelConfig(
            model_class="code_review",
            model_name="claude-3-5-sonnet-20241022",
            temperature=0.5,
            max_tokens=2048
        )
        assert config.model_class == "code_review"
        assert config.model_name == "claude-3-5-sonnet-20241022"
        assert config.temperature == 0.5
        assert config.max_tokens == 2048
    
    def test_model_config_defaults(self) -> None:
        """Test ModelConfig with default values."""
        config = ModelConfig(model_class="structural_review")
        assert config.model_class == "structural_review"
        assert config.model_name is None
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
    
    def test_model_config_validation_temperature_bounds(self) -> None:
        """Test ModelConfig temperature validation."""
        # Valid temperatures
        ModelConfig(model_class="test", temperature=0.0)
        ModelConfig(model_class="test", temperature=1.0)
        ModelConfig(model_class="test", temperature=2.0)
        
        # Invalid temperatures
        with pytest.raises(ValueError):
            ModelConfig(model_class="test", temperature=-0.1)
        
        with pytest.raises(ValueError):
            ModelConfig(model_class="test", temperature=2.1)
    
    def test_model_config_validation_max_tokens(self) -> None:
        """Test ModelConfig max_tokens validation."""
        # Valid max_tokens
        ModelConfig(model_class="test", max_tokens=1)
        ModelConfig(model_class="test", max_tokens=8192)
        
        # Invalid max_tokens
        with pytest.raises(ValueError):
            ModelConfig(model_class="test", max_tokens=0)
        
        with pytest.raises(ValueError):
            ModelConfig(model_class="test", max_tokens=-1)


class TestModelResolver:
    """Tests for ModelResolver class."""
    
    @pytest.fixture
    def temp_model_map_path(self) -> Path:
        """Create a temporary path for model map file."""
        temp_dir = tempfile.mkdtemp()
        return Path(temp_dir) / "model_map.yml"
    
    @pytest.fixture
    def sample_model_map(self) -> dict[str, dict[str, any]]:
        """Sample model map data."""
        return {
            "code_review": {
                "model_name": "claude-3-5-sonnet-20241022",
                "temperature": 0.3,
                "max_tokens": 4096
            },
            "structural_review": {
                "model_name": "claude-3-opus-20240229",
                "temperature": 0.5,
                "max_tokens": 8192
            },
            "adversarial_review": {
                "model_name": "claude-3-haiku-20240307",
                "temperature": 0.7,
                "max_tokens": 2048
            }
        }
    
    def test_resolve_model_default_mapping(self, temp_model_map_path: Path, sample_model_map: dict) -> None:
        """Test resolve_model with default mapping."""
        # Create model map file
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            yaml.safe_dump(sample_model_map, f)
        
        resolver = ModelResolver(temp_model_map_path)
        config = resolver.resolve_model("code_review")
        
        assert config.model_class == "code_review"
        assert config.model_name == "claude-3-5-sonnet-20241022"
        assert config.temperature == 0.3
        assert config.max_tokens == 4096
    
    def test_resolve_model_project_override(self, temp_model_map_path: Path, sample_model_map: dict) -> None:
        """Test resolve_model with project-specific overrides."""
        # Create model map file
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            yaml.safe_dump(sample_model_map, f)
        
        project_overrides = {
            "reviewers": {
                "engineer": {
                    "model_class": "code_review",
                    "model_name": "custom-model",
                    "temperature": 0.2,
                    "max_tokens": 2000
                }
            }
        }
        
        resolver = ModelResolver(temp_model_map_path)
        config = resolver.resolve_model("code_review", project_overrides)
        
        assert config.model_class == "code_review"
        assert config.model_name == "custom-model"
        assert config.temperature == 0.2
        assert config.max_tokens == 2000
    
    def test_resolve_model_partial_project_override(self, temp_model_map_path: Path, sample_model_map: dict) -> None:
        """Test resolve_model with partial project overrides."""
        # Create model map file
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            yaml.safe_dump(sample_model_map, f)
        
        project_overrides = {
            "reviewers": {
                "engineer": {
                    "model_class": "code_review",
                    "temperature": 0.1  # Only override temperature
                }
            }
        }
        
        resolver = ModelResolver(temp_model_map_path)
        config = resolver.resolve_model("code_review", project_overrides)
        
        assert config.model_class == "code_review"
        assert config.model_name == "claude-3-5-sonnet-20241022"  # From default
        assert config.temperature == 0.1  # Overridden
        assert config.max_tokens == 4096  # From default
    
    def test_resolve_model_unknown_class(self, temp_model_map_path: Path, sample_model_map: dict) -> None:
        """Test resolve_model with unknown model class."""
        # Create model map file
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            yaml.safe_dump(sample_model_map, f)
        
        resolver = ModelResolver(temp_model_map_path)
        
        with pytest.raises(ModelResolutionError, match="Unknown model class: unknown_class"):
            resolver.resolve_model("unknown_class")
    
    def test_resolve_model_missing_map_file(self, temp_model_map_path: Path) -> None:
        """Test ModelResolver with missing model map file creates default."""
        # Don't create the file - let resolver create default
        resolver = ModelResolver(temp_model_map_path)
        
        # Should create default map and be able to resolve standard classes
        config = resolver.resolve_model("code_review")
        assert config.model_class == "code_review"
        assert config.model_name == "claude-3-5-sonnet-20241022"
        
        # Verify file was created
        assert temp_model_map_path.exists()
    
    def test_resolver_invalid_yaml(self, temp_model_map_path: Path) -> None:
        """Test ModelResolver with invalid YAML file."""
        # Create invalid YAML file
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            f.write("invalid: yaml: content: [")
        
        with pytest.raises(ModelResolutionError, match="Failed to load model map"):
            ModelResolver(temp_model_map_path)
    
    def test_resolver_non_dict_yaml(self, temp_model_map_path: Path) -> None:
        """Test ModelResolver with non-dictionary YAML content."""
        # Create YAML file with non-dict content
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            yaml.safe_dump(["not", "a", "dict"], f)
        
        with pytest.raises(ModelResolutionError, match="Model map must be a dictionary"):
            ModelResolver(temp_model_map_path)
    
    @patch("builtins.open", side_effect=OSError("Permission denied"))
    def test_resolver_file_read_error(self, mock_file: any, temp_model_map_path: Path) -> None:
        """Test ModelResolver with file read error."""
        # Create file first so it exists
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        temp_model_map_path.touch()
        
        with pytest.raises(ModelResolutionError, match="Failed to load model map"):
            ModelResolver(temp_model_map_path)
    
    def test_model_config_validation_in_resolve(self, temp_model_map_path: Path) -> None:
        """Test that invalid model configurations are caught during resolution."""
        # Create model map with invalid configuration
        invalid_map = {
            "bad_config": {
                "temperature": 5.0,  # Invalid temperature
                "max_tokens": -1     # Invalid max_tokens
            }
        }
        
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            yaml.safe_dump(invalid_map, f)
        
        resolver = ModelResolver(temp_model_map_path)
        
        with pytest.raises(ModelResolutionError, match="Invalid model configuration"):
            resolver.resolve_model("bad_config")
    
    def test_default_model_map_creation_error(self, temp_model_map_path: Path) -> None:
        """Test error handling when default model map cannot be created."""
        # Make parent directory read-only
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        temp_model_map_path.parent.chmod(0o444)
        
        try:
            with pytest.raises(ModelResolutionError, match="Failed to load model map"):
                ModelResolver(temp_model_map_path)
        finally:
            # Clean up - restore write permissions
            temp_model_map_path.parent.chmod(0o755)
    
    @patch("yaml.safe_dump", side_effect=OSError("Write error"))
    def test_default_model_map_write_error(self, mock_dump: any, temp_model_map_path: Path) -> None:
        """Test error handling when writing default model map fails."""
        with pytest.raises(ModelResolutionError, match="Failed to create default model map"):
            ModelResolver(temp_model_map_path)
    
    def test_resolve_model_no_matching_reviewer_override(self, temp_model_map_path: Path, sample_model_map: dict) -> None:
        """Test resolve_model when project overrides don't match the model class."""
        # Create model map file
        temp_model_map_path.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_model_map_path, 'w') as f:
            yaml.safe_dump(sample_model_map, f)
        
        project_overrides = {
            "reviewers": {
                "architect": {  # Different reviewer
                    "model_class": "structural_review",  # Different model class
                    "temperature": 0.1
                }
            }
        }
        
        resolver = ModelResolver(temp_model_map_path)
        config = resolver.resolve_model("code_review", project_overrides)
        
        # Should use defaults since no matching override
        assert config.model_class == "code_review"
        assert config.model_name == "claude-3-5-sonnet-20241022"
        assert config.temperature == 0.3
        assert config.max_tokens == 4096