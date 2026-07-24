"""Tests for stonehaven/registry.py module."""

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from stonehaven.registry import ProjectRegistry, RegistrationError
from verdict_store.client import ProjectRecord, VerdictStoreClient


@pytest.fixture
def mock_client() -> Mock:
    """Mock VerdictStoreClient for testing."""
    return Mock(spec=VerdictStoreClient)


@pytest.fixture
def registry(mock_client: Mock) -> ProjectRegistry:
    """ProjectRegistry instance with mocked client."""
    return ProjectRegistry(mock_client)


class TestProjectRegistry:
    """Test cases for ProjectRegistry class."""

    def test_register_project_success(self, registry: ProjectRegistry, mock_client: Mock) -> None:
        """Test successful project registration."""
        stonehaven_id = str(uuid.uuid4())
        repo = "org/test-repo"
        project_name = "Test Project"
        expected_id = 42

        mock_client.create_project.return_value = expected_id

        result = registry.register_project(stonehaven_id, repo, project_name)

        assert result == expected_id
        mock_client.create_project.assert_called_once_with(stonehaven_id, repo, project_name)

    def test_register_project_duplicate_stonehaven_id(
        self, registry: ProjectRegistry, mock_client: Mock
    ) -> None:
        """Test registration fails with duplicate stonehaven_id."""
        stonehaven_id = str(uuid.uuid4())
        repo = "org/test-repo"
        project_name = "Test Project"

        mock_client.create_project.side_effect = sqlite3.IntegrityError(
            "UNIQUE constraint failed: projects.stonehaven_id"
        )

        with pytest.raises(RegistrationError, match="already registered"):
            registry.register_project(stonehaven_id, repo, project_name)

        mock_client.create_project.assert_called_once_with(stonehaven_id, repo, project_name)

    def test_register_project_duplicate_repo(
        self, registry: ProjectRegistry, mock_client: Mock
    ) -> None:
        """Test registration fails with duplicate repo."""
        stonehaven_id = str(uuid.uuid4())
        repo = "org/test-repo"
        project_name = "Test Project"

        mock_client.create_project.side_effect = sqlite3.IntegrityError(
            "UNIQUE constraint failed: projects.repo"
        )

        with pytest.raises(RegistrationError, match="already registered"):
            registry.register_project(stonehaven_id, repo, project_name)

        mock_client.create_project.assert_called_once_with(stonehaven_id, repo, project_name)

    def test_register_project_invalid_uuid(
        self, registry: ProjectRegistry, mock_client: Mock
    ) -> None:
        """Test registration fails with invalid UUID."""
        invalid_uuid = "not-a-uuid"
        repo = "org/test-repo"
        project_name = "Test Project"

        with pytest.raises(RegistrationError, match="Invalid UUID4 format"):
            registry.register_project(invalid_uuid, repo, project_name)

        # Should not call client if UUID is invalid
        mock_client.create_project.assert_not_called()

    def test_register_project_database_error(
        self, registry: ProjectRegistry, mock_client: Mock
    ) -> None:
        """Test registration fails with database error."""
        stonehaven_id = str(uuid.uuid4())
        repo = "org/test-repo"
        project_name = "Test Project"

        mock_client.create_project.side_effect = sqlite3.Error("Database connection failed")

        with pytest.raises(RegistrationError, match="Database error during registration"):
            registry.register_project(stonehaven_id, repo, project_name)

        mock_client.create_project.assert_called_once_with(stonehaven_id, repo, project_name)

    def test_get_project_found(self, registry: ProjectRegistry, mock_client: Mock) -> None:
        """Test getting an existing project."""
        repo = "org/test-repo"
        expected_record = ProjectRecord(
            id=1,
            stonehaven_id=str(uuid.uuid4()),
            repo=repo,
            project_name="Test Project",
        )

        mock_client.get_project_by_repo.return_value = expected_record

        result = registry.get_project(repo)

        assert result == expected_record
        mock_client.get_project_by_repo.assert_called_once_with(repo)

    def test_get_project_not_found(self, registry: ProjectRegistry, mock_client: Mock) -> None:
        """Test getting a non-existent project."""
        repo = "org/nonexistent-repo"

        mock_client.get_project_by_repo.return_value = None

        result = registry.get_project(repo)

        assert result is None
        mock_client.get_project_by_repo.assert_called_once_with(repo)

    def test_get_project_database_error(
        self, registry: ProjectRegistry, mock_client: Mock
    ) -> None:
        """Test get_project with database error."""
        repo = "org/test-repo"

        mock_client.get_project_by_repo.side_effect = sqlite3.Error("Database connection failed")

        with pytest.raises(RegistrationError, match="Database error during lookup"):
            registry.get_project(repo)

        mock_client.get_project_by_repo.assert_called_once_with(repo)

    def test_list_projects_empty(self, registry: ProjectRegistry) -> None:
        """Test listing projects when none exist (currently raises NotImplementedError)."""
        with pytest.raises(NotImplementedError, match="additional functionality"):
            registry.list_projects()

    def test_list_projects_multiple(self, registry: ProjectRegistry) -> None:
        """Test listing multiple projects (currently raises NotImplementedError)."""
        with pytest.raises(NotImplementedError, match="additional functionality"):
            registry.list_projects()


class TestRegistrationError:
    """Test cases for RegistrationError exception."""

    def test_registration_error_creation(self) -> None:
        """Test RegistrationError can be created and raised."""
        message = "Test error message"
        error = RegistrationError(message)
        
        assert str(error) == message
        assert isinstance(error, Exception)

    def test_registration_error_with_cause(self) -> None:
        """Test RegistrationError with underlying cause."""
        cause = sqlite3.IntegrityError("Database constraint")
        
        with pytest.raises(RegistrationError) as exc_info:
            try:
                raise cause
            except sqlite3.IntegrityError as e:
                raise RegistrationError("Registration failed") from e
        
        assert exc_info.value.__cause__ == cause