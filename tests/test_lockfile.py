"""Tests for renderer.lockfile module."""

import tempfile
from pathlib import Path

import pytest

from renderer.lockfile import read_lock, write_lock, update_template_version


class TestReadLock:
    """Test read_lock function."""
    
    def test_read_lock_valid_file(self, tmp_path: Path) -> None:
        """Test reading valid lock file."""
        lock_file = tmp_path / "templates_lock.yml"
        lock_file.write_text("engineer: 1.2.3\narchitect: 2.1.0\n")
        
        result = read_lock(lock_file)
        
        assert result == {"engineer": "1.2.3", "architect": "2.1.0"}
    
    def test_read_lock_file_not_found_returns_empty(self, tmp_path: Path) -> None:
        """Test reading non-existent file returns empty dict."""
        lock_file = tmp_path / "nonexistent.yml"
        
        result = read_lock(lock_file)
        
        assert result == {}
    
    def test_read_lock_empty_file(self, tmp_path: Path) -> None:
        """Test reading empty file returns empty dict."""
        lock_file = tmp_path / "empty_lock.yml"
        lock_file.write_text("")
        
        result = read_lock(lock_file)
        
        assert result == {}
    
    def test_read_lock_null_yaml(self, tmp_path: Path) -> None:
        """Test reading file with null YAML content."""
        lock_file = tmp_path / "null_lock.yml"
        lock_file.write_text("null")
        
        result = read_lock(lock_file)
        
        assert result == {}


class TestWriteLock:
    """Test write_lock function."""
    
    def test_write_lock_creates_valid_yaml(self, tmp_path: Path) -> None:
        """Test writing lock file creates valid YAML."""
        lock_file = tmp_path / "new_lock.yml"
        versions = {"engineer": "1.0.0", "architect": "2.0.0"}
        
        write_lock(lock_file, versions)
        
        assert lock_file.exists()
        content = lock_file.read_text()
        assert "architect: 2.0.0" in content
        assert "engineer: 1.0.0" in content
        
        # Verify it can be read back correctly
        result = read_lock(lock_file)
        assert result == versions
    
    def test_write_lock_creates_parent_directory(self, tmp_path: Path) -> None:
        """Test writing lock file creates parent directories."""
        nested_path = tmp_path / "nested" / "dir" / "lock.yml"
        versions = {"test": "1.0.0"}
        
        write_lock(nested_path, versions)
        
        assert nested_path.exists()
        assert nested_path.parent.exists()
        result = read_lock(nested_path)
        assert result == versions
    
    def test_write_lock_overwrites_existing(self, tmp_path: Path) -> None:
        """Test writing lock file overwrites existing content."""
        lock_file = tmp_path / "existing.yml"
        lock_file.write_text("old: data")
        
        new_versions = {"engineer": "2.0.0"}
        write_lock(lock_file, new_versions)
        
        result = read_lock(lock_file)
        assert result == new_versions
        assert "old" not in lock_file.read_text()
    
    def test_write_lock_empty_dict(self, tmp_path: Path) -> None:
        """Test writing empty versions dict."""
        lock_file = tmp_path / "empty.yml"
        
        write_lock(lock_file, {})
        
        assert lock_file.exists()
        result = read_lock(lock_file)
        assert result == {}


class TestUpdateTemplateVersion:
    """Test update_template_version function."""
    
    def test_update_template_version_existing_template(self, tmp_path: Path) -> None:
        """Test updating version for existing template."""
        lock_file = tmp_path / "update_test.yml"
        initial_versions = {"engineer": "1.0.0", "architect": "2.0.0"}
        write_lock(lock_file, initial_versions)
        
        update_template_version(lock_file, "engineer", "1.1.0")
        
        result = read_lock(lock_file)
        assert result == {"engineer": "1.1.0", "architect": "2.0.0"}
    
    def test_update_template_version_new_template(self, tmp_path: Path) -> None:
        """Test adding version for new template."""
        lock_file = tmp_path / "new_template_test.yml"
        initial_versions = {"engineer": "1.0.0"}
        write_lock(lock_file, initial_versions)
        
        update_template_version(lock_file, "sre", "1.0.0")
        
        result = read_lock(lock_file)
        assert result == {"engineer": "1.0.0", "sre": "1.0.0"}
    
    def test_update_template_version_nonexistent_file(self, tmp_path: Path) -> None:
        """Test updating template version when lock file doesn't exist."""
        lock_file = tmp_path / "nonexistent.yml"
        
        update_template_version(lock_file, "engineer", "1.0.0")
        
        result = read_lock(lock_file)
        assert result == {"engineer": "1.0.0"}


class TestAtomicWrite:
    """Test atomic write behavior."""
    
    def test_atomic_write_on_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that failed writes don't corrupt existing file."""
        lock_file = tmp_path / "atomic_test.yml"
        initial_versions = {"engineer": "1.0.0"}
        write_lock(lock_file, initial_versions)
        
        # Mock yaml.safe_dump to raise an exception
        import yaml
        original_dump = yaml.safe_dump
        
        def mock_dump(*args, **kwargs):
            raise OSError("Simulated write failure")
        
        monkeypatch.setattr(yaml, "safe_dump", mock_dump)
        
        # Attempt write that will fail
        with pytest.raises(OSError, match="Simulated write failure"):
            write_lock(lock_file, {"engineer": "2.0.0"})
        
        # Original file should be unchanged
        result = read_lock(lock_file)
        assert result == initial_versions
        
        # Restore original function and verify normal operation still works
        monkeypatch.setattr(yaml, "safe_dump", original_dump)
        write_lock(lock_file, {"engineer": "2.0.0"})
        result = read_lock(lock_file)
        assert result == {"engineer": "2.0.0"}
    
    def test_no_temp_files_left_behind(self, tmp_path: Path) -> None:
        """Test that temporary files are cleaned up after successful write."""
        lock_file = tmp_path / "cleanup_test.yml"
        
        # Count files before write
        files_before = list(tmp_path.iterdir())
        
        write_lock(lock_file, {"test": "1.0.0"})
        
        # Count files after write
        files_after = list(tmp_path.iterdir())
        
        # Should only have one more file (the lock file itself)
        assert len(files_after) == len(files_before) + 1
        assert lock_file in files_after
        
        # No .tmp files should remain
        tmp_files = [f for f in files_after if f.name.endswith('.tmp')]
        assert len(tmp_files) == 0