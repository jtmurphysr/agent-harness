"""Project registry CRUD operations.

This module provides the ProjectRegistry class for managing project
registration with the Stonehaven listener. The registry manages project
metadata and serves as the central authority for which projects are
actively managed by the harness.

⚠️ WARNING: Registry = webhook registration — Registering a repo with Stonehaven IS adding it to the fleet
⚠️ WARNING: Stonehaven ID is UUID4 — Used as disaster-recovery join key in .factory/harness.toml
"""

import sqlite3
import uuid

from verdict_store.client import ProjectRecord, VerdictStoreClient


class RegistrationError(Exception):
    """Raised when project registration fails."""


class ProjectRegistry:
    """Project registry for managing Stonehaven fleet projects.

    This class provides CRUD operations for project registration,
    wrapping the VerdictStoreClient to provide a focused interface
    for project management operations.
    """

    def __init__(self, client: VerdictStoreClient) -> None:
        """Initialize registry with verdict store client.

        Args:
            client: VerdictStoreClient instance for database operations
        """
        self.client = client

    def register_project(self, stonehaven_id: str, repo: str, project_name: str) -> int:
        """Register a new project with the fleet.

        Args:
            stonehaven_id: UUID4 identifier for Stonehaven registration
            repo: Repository name in org/name format
            project_name: Human-readable project name

        Returns:
            The ID of the created project record

        Raises:
            RegistrationError: If registration fails due to conflicts or validation
        """
        # Validate UUID format
        try:
            uuid.UUID(stonehaven_id, version=4)
        except ValueError as e:
            raise RegistrationError(f"Invalid UUID4 format for stonehaven_id: {e}") from e

        try:
            project_id = self.client.create_project(stonehaven_id, repo, project_name)
            return project_id
        except sqlite3.IntegrityError as e:
            if "stonehaven_id" in str(e):
                raise RegistrationError(
                    f"Project with stonehaven_id '{stonehaven_id}' already registered"
                ) from e
            elif "repo" in str(e):
                raise RegistrationError(f"Repository '{repo}' already registered") from e
            else:
                raise RegistrationError(f"Registration failed due to constraint: {e}") from e
        except sqlite3.Error as e:
            raise RegistrationError(f"Database error during registration: {e}") from e

    def get_project(self, repo: str) -> ProjectRecord | None:
        """Get project record by repository name.

        Args:
            repo: Repository name in org/name format

        Returns:
            ProjectRecord if found, None otherwise

        Raises:
            RegistrationError: If database operation fails
        """
        try:
            return self.client.get_project_by_repo(repo)
        except sqlite3.Error as e:
            raise RegistrationError(f"Database error during lookup: {e}") from e

    def list_projects(self) -> list[ProjectRecord]:
        """List all registered projects.

        Returns:
            List of all project records, ordered by registration time

        Raises:
            RegistrationError: If database operation fails
        """
        # VerdictStoreClient doesn't have a list_projects method yet.
        # This is a temporary stub until the method is added to VerdictStoreClient.
        # The registry must not directly access the database per architectural constraints.
        raise NotImplementedError(
            "list_projects requires additional functionality in VerdictStoreClient"
        )


__all__ = ["ProjectRegistry", "RegistrationError"]
