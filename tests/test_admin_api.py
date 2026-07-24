"""Tests for stonehaven admin API endpoints.

Comprehensive test suite for all admin API endpoints including
authentication, pagination, error handling, and data validation.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stonehaven.admin_api import create_admin_router
from stonehaven.registry import ProjectRegistry, RegistrationError
from verdict_store.client import FindingRecord, ProjectRecord, VerdictRecord, VerdictStoreClient


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Create a temporary database path for testing."""
    return tmp_path / "test_verdicts.db"


@pytest.fixture
def verdict_store_client(temp_db_path: Path) -> VerdictStoreClient:
    """Create a VerdictStoreClient for testing."""
    return VerdictStoreClient(temp_db_path)


@pytest.fixture
def project_registry(verdict_store_client: VerdictStoreClient) -> ProjectRegistry:
    """Create a ProjectRegistry for testing."""
    return ProjectRegistry(verdict_store_client)


@pytest.fixture
def test_app(project_registry: ProjectRegistry) -> FastAPI:
    """Create a test FastAPI app with admin router."""
    app = FastAPI()
    admin_router = create_admin_router(project_registry)
    app.include_router(admin_router)
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create a test client for the FastAPI app."""
    return TestClient(test_app)


@pytest.fixture
def auth_headers() -> Dict[str, str]:
    """Authentication headers for protected endpoints."""
    return {"Authorization": "Bearer admin-token"}


@pytest.fixture
def sample_project(verdict_store_client: VerdictStoreClient) -> ProjectRecord:
    """Create a sample project in the database."""
    stonehaven_id = str(uuid.uuid4())
    project_id = verdict_store_client.create_project(
        stonehaven_id=stonehaven_id,
        repo="testorg/testrepo",
        project_name="Test Project",
    )
    return verdict_store_client.get_project_by_id(project_id)


@pytest.fixture
def sample_verdict(
    verdict_store_client: VerdictStoreClient, sample_project: ProjectRecord
) -> VerdictRecord:
    """Create a sample verdict in the database."""
    verdict = VerdictRecord(
        delivery_id="test-delivery-123",
        project_id=sample_project.id,
        pr_number=42,
        pr_sha="abc123def456",
        pr_size_lines=150,
        reviewer="engineer",
        severity="WARN",
        good="Good things found",
        bad="Bad things found",
        ugly="Ugly things found",
        closing_question="What about X?",
        raw_response="Full reviewer response",
        template_version="v1.0.0",
    )
    verdict_id = verdict_store_client.write_verdict(verdict)
    verdict.id = verdict_id
    return verdict


@pytest.fixture
def sample_findings(
    verdict_store_client: VerdictStoreClient, sample_verdict: VerdictRecord
) -> list[FindingRecord]:
    """Create sample findings in the database."""
    findings = [
        FindingRecord(
            verdict_id=sample_verdict.id,
            bucket="bad",
            text="Security issue found",
            severity="BLOCK",
            invariant_id="sec_001",
        ),
        FindingRecord(
            verdict_id=sample_verdict.id,
            bucket="ugly",
            text="Code smell detected",
            severity="WARN",
            invariant_id="code_quality_001",
        ),
    ]
    verdict_store_client.write_findings(sample_verdict.id, findings)
    return findings


class TestProjectRegistration:
    """Tests for project registration endpoint."""

    def test_register_project_endpoint_success(
        self, client: TestClient, auth_headers: Dict[str, str]
    ) -> None:
        """Test successful project registration."""
        stonehaven_id = str(uuid.uuid4())
        request_data = {
            "stonehaven_id": stonehaven_id,
            "repo": "testorg/newrepo",
            "project_name": "New Test Project",
        }

        response = client.post("/api/v1/projects/register", json=request_data, headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Project registered successfully"
        assert data["stonehaven_id"] == stonehaven_id
        assert data["repo"] == "testorg/newrepo"
        assert "project_id" in data

    def test_register_project_endpoint_unauthorized(self, client: TestClient) -> None:
        """Test project registration without valid token."""
        request_data = {
            "stonehaven_id": str(uuid.uuid4()),
            "repo": "testorg/unauthorized",
            "project_name": "Unauthorized Project",
        }

        # No auth headers
        response = client.post("/api/v1/projects/register", json=request_data)
        assert response.status_code == 401

        # Invalid token
        invalid_headers = {"Authorization": "Bearer invalid-token"}
        response = client.post("/api/v1/projects/register", json=request_data, headers=invalid_headers)
        assert response.status_code == 401

    def test_register_project_duplicate_repo(
        self, client: TestClient, auth_headers: Dict[str, str], sample_project: ProjectRecord
    ) -> None:
        """Test registration with duplicate repository."""
        request_data = {
            "stonehaven_id": str(uuid.uuid4()),
            "repo": sample_project.repo,  # Duplicate repo
            "project_name": "Duplicate Repo Project",
        }

        response = client.post("/api/v1/projects/register", json=request_data, headers=auth_headers)
        
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]

    def test_register_project_duplicate_stonehaven_id(
        self, client: TestClient, auth_headers: Dict[str, str], sample_project: ProjectRecord
    ) -> None:
        """Test registration with duplicate stonehaven_id."""
        request_data = {
            "stonehaven_id": sample_project.stonehaven_id,  # Duplicate stonehaven_id
            "repo": "testorg/differentrepo",
            "project_name": "Different Project",
        }

        response = client.post("/api/v1/projects/register", json=request_data, headers=auth_headers)
        
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"]

    def test_register_project_invalid_uuid(
        self, client: TestClient, auth_headers: Dict[str, str]
    ) -> None:
        """Test registration with invalid UUID format."""
        request_data = {
            "stonehaven_id": "not-a-valid-uuid",
            "repo": "testorg/invaliduuid",
            "project_name": "Invalid UUID Project",
        }

        response = client.post("/api/v1/projects/register", json=request_data, headers=auth_headers)
        
        assert response.status_code == 400
        assert "Invalid UUID4 format" in response.json()["detail"]


class TestProjectListing:
    """Tests for project listing endpoint."""

    def test_get_projects_endpoint(
        self, client: TestClient, sample_project: ProjectRecord
    ) -> None:
        """Test retrieving list of projects."""
        response = client.get("/api/v1/projects")
        
        assert response.status_code == 200
        projects = response.json()
        assert len(projects) >= 1
        
        # Find our sample project
        project = next((p for p in projects if p["id"] == sample_project.id), None)
        assert project is not None
        assert project["repo"] == sample_project.repo
        assert project["project_name"] == sample_project.project_name
        assert project["stonehaven_id"] == sample_project.stonehaven_id
        assert project["active"] == sample_project.active

    def test_get_projects_empty_list(self, client: TestClient) -> None:
        """Test retrieving projects when none exist."""
        response = client.get("/api/v1/projects")
        
        assert response.status_code == 200
        projects = response.json()
        assert isinstance(projects, list)


class TestProjectVerdicts:
    """Tests for project verdicts endpoint."""

    def test_get_project_verdicts_paginated(
        self, client: TestClient, sample_project: ProjectRecord, sample_verdict: VerdictRecord
    ) -> None:
        """Test retrieving project verdicts with pagination."""
        response = client.get(f"/api/v1/projects/{sample_project.id}/verdicts?limit=10&offset=0")
        
        assert response.status_code == 200
        verdicts = response.json()
        assert len(verdicts) >= 1
        
        verdict = verdicts[0]
        assert verdict["id"] == sample_verdict.id
        assert verdict["delivery_id"] == sample_verdict.delivery_id
        assert verdict["pr_number"] == sample_verdict.pr_number
        assert verdict["reviewer"] == sample_verdict.reviewer
        assert verdict["severity"] == sample_verdict.severity

    def test_get_project_verdicts_pagination_limits(
        self, client: TestClient, sample_project: ProjectRecord
    ) -> None:
        """Test pagination parameter validation."""
        # Test limit too high
        response = client.get(f"/api/v1/projects/{sample_project.id}/verdicts?limit=2000")
        assert response.status_code == 422

        # Test limit too low
        response = client.get(f"/api/v1/projects/{sample_project.id}/verdicts?limit=0")
        assert response.status_code == 422

        # Test negative offset
        response = client.get(f"/api/v1/projects/{sample_project.id}/verdicts?offset=-1")
        assert response.status_code == 422

    def test_get_project_verdicts_nonexistent_project(self, client: TestClient) -> None:
        """Test retrieving verdicts for nonexistent project."""
        response = client.get("/api/v1/projects/99999/verdicts")
        
        assert response.status_code == 200
        verdicts = response.json()
        assert len(verdicts) == 0


class TestProjectStats:
    """Tests for project statistics endpoint."""

    def test_get_project_stats(
        self, 
        client: TestClient, 
        sample_project: ProjectRecord, 
        sample_verdict: VerdictRecord,
        sample_findings: list[FindingRecord]
    ) -> None:
        """Test retrieving project statistics."""
        response = client.get(f"/api/v1/projects/{sample_project.id}/stats")
        
        assert response.status_code == 200
        stats = response.json()
        
        assert stats["project_id"] == sample_project.id
        assert stats["total_verdicts"] >= 1
        assert stats["warn_count"] >= 1  # Our sample verdict is WARN
        assert isinstance(stats["block_rate"], float)
        assert isinstance(stats["warn_rate"], float)
        assert isinstance(stats["avg_findings_per_pr"], float)

    def test_get_project_stats_nonexistent_project(self, client: TestClient) -> None:
        """Test stats for nonexistent project."""
        response = client.get("/api/v1/projects/99999/stats")
        
        assert response.status_code == 200
        stats = response.json()
        assert stats["total_verdicts"] == 0


class TestFleetStats:
    """Tests for fleet statistics endpoint."""

    def test_get_fleet_stats(
        self,
        client: TestClient,
        sample_project: ProjectRecord,
        sample_verdict: VerdictRecord,
        sample_findings: list[FindingRecord],
    ) -> None:
        """Test retrieving fleet-wide statistics."""
        response = client.get("/api/v1/fleet/stats")
        
        assert response.status_code == 200
        stats = response.json()
        
        assert stats["total_projects"] >= 1
        assert stats["active_projects"] >= 1
        assert stats["total_verdicts"] >= 1
        assert stats["total_findings"] >= len(sample_findings)
        assert isinstance(stats["avg_block_rate"], float)
        assert isinstance(stats["avg_warn_rate"], float)
        assert isinstance(stats["avg_findings_per_pr"], float)

    def test_get_fleet_stats_empty_fleet(self, client: TestClient) -> None:
        """Test fleet stats with empty database."""
        response = client.get("/api/v1/fleet/stats")
        
        assert response.status_code == 200
        stats = response.json()
        assert stats["total_projects"] == 0
        assert stats["active_projects"] == 0


class TestFleetFindings:
    """Tests for fleet findings endpoint."""

    def test_get_fleet_findings_filtered(
        self,
        client: TestClient,
        sample_project: ProjectRecord,
        sample_verdict: VerdictRecord,
        sample_findings: list[FindingRecord],
    ) -> None:
        """Test retrieving fleet findings with filters."""
        # Test bucket filter
        response = client.get("/api/v1/fleet/findings?bucket=bad")
        assert response.status_code == 200
        findings = response.json()
        assert all(finding["bucket"] == "bad" for finding in findings)

        # Test severity filter
        response = client.get("/api/v1/fleet/findings?severity=BLOCK")
        assert response.status_code == 200
        findings = response.json()
        assert all(finding["severity"] == "BLOCK" for finding in findings)

        # Test combined filters
        response = client.get("/api/v1/fleet/findings?bucket=bad&severity=BLOCK")
        assert response.status_code == 200
        findings = response.json()
        assert all(
            finding["bucket"] == "bad" and finding["severity"] == "BLOCK" 
            for finding in findings
        )

    def test_get_fleet_findings_pagination(
        self,
        client: TestClient,
        sample_project: ProjectRecord,
        sample_verdict: VerdictRecord,
        sample_findings: list[FindingRecord],
    ) -> None:
        """Test fleet findings pagination."""
        # Test with limit
        response = client.get("/api/v1/fleet/findings?limit=1")
        assert response.status_code == 200
        findings = response.json()
        assert len(findings) <= 1

        # Test with offset
        response = client.get("/api/v1/fleet/findings?offset=0&limit=100")
        assert response.status_code == 200


class TestInvariantFindings:
    """Tests for invariant-specific findings endpoint."""

    def test_get_invariant_findings(
        self,
        client: TestClient,
        sample_project: ProjectRecord,
        sample_verdict: VerdictRecord,
        sample_findings: list[FindingRecord],
    ) -> None:
        """Test retrieving findings for a specific invariant."""
        invariant_id = "sec_001"
        
        response = client.get(f"/api/v1/fleet/invariants/{invariant_id}/findings")
        assert response.status_code == 200
        
        findings = response.json()
        assert all(finding["invariant_id"] == invariant_id for finding in findings)

    def test_get_invariant_findings_nonexistent(self, client: TestClient) -> None:
        """Test retrieving findings for nonexistent invariant."""
        response = client.get("/api/v1/fleet/invariants/nonexistent/findings")
        assert response.status_code == 200
        
        findings = response.json()
        assert len(findings) == 0


class TestInvariantCoverage:
    """Tests for invariant coverage endpoint."""

    def test_get_invariant_coverage(
        self,
        client: TestClient,
        sample_project: ProjectRecord,
        sample_verdict: VerdictRecord,
        sample_findings: list[FindingRecord],
    ) -> None:
        """Test retrieving invariant coverage statistics."""
        response = client.get("/api/v1/fleet/invariants/coverage")
        assert response.status_code == 200
        
        coverage = response.json()
        assert isinstance(coverage, list)
        
        if coverage:  # If we have coverage data
            item = coverage[0]
            assert "invariant_id" in item
            assert "total_findings" in item
            assert "projects_affected" in item
            assert "avg_severity_score" in item
            assert isinstance(item["total_findings"], int)
            assert isinstance(item["projects_affected"], int)
            assert isinstance(item["avg_severity_score"], float)

    def test_get_invariant_coverage_empty(self, client: TestClient) -> None:
        """Test invariant coverage with no data."""
        response = client.get("/api/v1/fleet/invariants/coverage")
        assert response.status_code == 200
        
        coverage = response.json()
        assert isinstance(coverage, list)


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    @patch("stonehaven.registry.ProjectRegistry.register_project")
    def test_registration_database_error(
        self, mock_register: Mock, client: TestClient, auth_headers: Dict[str, str]
    ) -> None:
        """Test handling of database errors during registration."""
        mock_register.side_effect = RegistrationError("Database connection failed")
        
        request_data = {
            "stonehaven_id": str(uuid.uuid4()),
            "repo": "testorg/dberror",
            "project_name": "DB Error Project",
        }
        
        response = client.post("/api/v1/projects/register", json=request_data, headers=auth_headers)
        assert response.status_code == 400
        assert "Database connection failed" in response.json()["detail"]

    def test_malformed_request_data(
        self, client: TestClient, auth_headers: Dict[str, str]
    ) -> None:
        """Test handling of malformed request data."""
        # Missing required field
        request_data = {
            "stonehaven_id": str(uuid.uuid4()),
            "repo": "testorg/incomplete",
            # Missing project_name
        }
        
        response = client.post("/api/v1/projects/register", json=request_data, headers=auth_headers)
        assert response.status_code == 422

    def test_invalid_json(self, client: TestClient, auth_headers: Dict[str, str]) -> None:
        """Test handling of invalid JSON in request."""
        response = client.post(
            "/api/v1/projects/register",
            data="invalid json",
            headers={**auth_headers, "Content-Type": "application/json"},
        )
        assert response.status_code == 422


class TestSecurityFeatures:
    """Tests for security-related functionality."""

    def test_webhook_secrets_not_returned(
        self, client: TestClient, sample_project: ProjectRecord
    ) -> None:
        """Test that webhook secrets are never returned in API responses."""
        # Get project details
        response = client.get("/api/v1/projects")
        assert response.status_code == 200
        
        projects = response.json()
        for project in projects:
            # Check that no field contains secret-like information
            for field_name, field_value in project.items():
                if isinstance(field_value, str):
                    assert "secret" not in field_name.lower()
                    assert "token" not in field_name.lower()
                    assert "key" not in field_name.lower()

    def test_bearer_token_validation_edge_cases(self, client: TestClient) -> None:
        """Test edge cases in bearer token validation."""
        request_data = {
            "stonehaven_id": str(uuid.uuid4()),
            "repo": "testorg/tokentest",
            "project_name": "Token Test Project",
        }
        
        # Empty token
        headers = {"Authorization": "Bearer "}
        response = client.post("/api/v1/projects/register", json=request_data, headers=headers)
        assert response.status_code == 401
        
        # Malformed authorization header
        headers = {"Authorization": "NotBearer admin-token"}
        response = client.post("/api/v1/projects/register", json=request_data, headers=headers)
        assert response.status_code == 401