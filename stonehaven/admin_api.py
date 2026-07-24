"""FastAPI admin endpoints for the Stonehaven listener.

This module provides the admin API for project registration and
verdict store queries. It implements all required endpoints for fleet
management and analytics.

⚠️ WARNING: Bearer token required for registration endpoint — Not unauthenticated
⚠️ WARNING: Webhook secrets never returned in API responses
⚠️ WARNING: Pagination required for verdicts endpoint to handle large result sets
"""

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from verdict_store.client import ProjectRecord, VerdictStoreClient

from .registry import ProjectRegistry, RegistrationError


class ProjectRegistrationRequest(BaseModel):
    """Request model for project registration."""

    stonehaven_id: str = Field(..., description="UUID4 identifier for Stonehaven registration")
    repo: str = Field(..., description="Repository name in org/name format")
    project_name: str = Field(..., description="Human-readable project name")


class ProjectResponse(BaseModel):
    """Response model for project information."""

    id: int
    stonehaven_id: str
    repo: str
    project_name: str
    registered_at: str
    harness_version: str | None
    active: bool


class VerdictResponse(BaseModel):
    """Response model for verdict information."""

    id: int
    delivery_id: str
    pr_number: int
    pr_sha: str
    pr_size_lines: int | None
    reviewer: str
    severity: str
    good: str | None
    bad: str | None
    ugly: str | None
    closing_question: str | None
    template_version: str | None
    reviewed_at: str


class ProjectStatsResponse(BaseModel):
    """Response model for project statistics."""

    project_id: int
    total_verdicts: int
    block_count: int
    warn_count: int
    pass_count: int
    block_rate: float
    warn_rate: float
    avg_findings_per_pr: float


class FleetStatsResponse(BaseModel):
    """Response model for fleet-wide statistics."""

    total_projects: int
    active_projects: int
    total_verdicts: int
    total_findings: int
    avg_block_rate: float
    avg_warn_rate: float
    avg_findings_per_pr: float


class FindingResponse(BaseModel):
    """Response model for finding information."""

    id: int
    verdict_id: int
    project_id: int
    project_name: str
    bucket: str
    text: str
    severity: str
    invariant_id: str | None
    reviewed_at: str


class InvariantCoverageResponse(BaseModel):
    """Response model for invariant coverage."""

    invariant_id: str
    total_findings: int
    projects_affected: int
    avg_severity_score: float


# Security setup
security = HTTPBearer()
security_dependency = Depends(security)


def verify_bearer_token(token: HTTPAuthorizationCredentials = security_dependency) -> str:
    """Verify bearer token for admin access.

    For now, this is a simple token check. In production,
    this would validate against a proper authentication system.
    """
    # Simple token validation - in production this would be more sophisticated
    if not token or token.credentials != "admin-token":
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    return token.credentials


def create_admin_router(registry: ProjectRegistry) -> APIRouter:
    """Create FastAPI router with all admin endpoints.

    Args:
        registry: ProjectRegistry instance for project operations

    Returns:
        Configured APIRouter with all endpoints
    """
    router = APIRouter(prefix="/api/v1", tags=["admin"])

    @router.post("/projects/register", response_model=dict[str, Any])
    async def register_project(
        request: ProjectRegistrationRequest,
        _token: str = Depends(verify_bearer_token),
    ) -> dict[str, Any]:
        """Register a new project with the fleet.

        Requires bearer token authentication.
        """
        try:
            project_id = registry.register_project(
                stonehaven_id=request.stonehaven_id,
                repo=request.repo,
                project_name=request.project_name,
            )
            return {
                "message": "Project registered successfully",
                "project_id": project_id,
                "stonehaven_id": request.stonehaven_id,
                "repo": request.repo,
            }
        except RegistrationError as e:
            if "already registered" in str(e):
                raise HTTPException(status_code=409, detail=str(e)) from e
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.get("/projects", response_model=list[ProjectResponse])
    async def get_projects() -> list[ProjectResponse]:
        """Get list of all registered projects."""
        try:
            # For now we'll implement this directly since registry.list_projects()
            # is not implemented yet
            projects = _get_all_projects_direct(registry.client)
            return [
                ProjectResponse(
                    id=project.id or 0,
                    stonehaven_id=project.stonehaven_id,
                    repo=project.repo,
                    project_name=project.project_name,
                    registered_at=project.registered_at.isoformat()
                    if project.registered_at
                    else "",
                    harness_version=project.harness_version,
                    active=project.active,
                )
                for project in projects
            ]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to retrieve projects: {e}") from e

    @router.get("/projects/{project_id}/verdicts", response_model=list[VerdictResponse])
    async def get_project_verdicts(
        project_id: int,
        limit: int = Query(100, ge=1, le=1000, description="Number of verdicts to return"),
        offset: int = Query(0, ge=0, description="Number of verdicts to skip"),
    ) -> list[VerdictResponse]:
        """Get verdicts for a specific project with pagination."""
        try:
            verdicts = registry.client.get_verdicts_for_project(
                project_id=project_id, limit=limit, offset=offset
            )
            return [
                VerdictResponse(
                    id=verdict.id or 0,
                    delivery_id=verdict.delivery_id,
                    pr_number=verdict.pr_number,
                    pr_sha=verdict.pr_sha,
                    pr_size_lines=verdict.pr_size_lines,
                    reviewer=verdict.reviewer,
                    severity=verdict.severity,
                    good=verdict.good,
                    bad=verdict.bad,
                    ugly=verdict.ugly,
                    closing_question=verdict.closing_question,
                    template_version=verdict.template_version,
                    reviewed_at=verdict.reviewed_at.isoformat() if verdict.reviewed_at else "",
                )
                for verdict in verdicts
            ]
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve verdicts for project {project_id}: {e}"
            ) from e

    @router.get("/projects/{project_id}/stats", response_model=ProjectStatsResponse)
    async def get_project_stats(project_id: int) -> ProjectStatsResponse:
        """Get statistics for a specific project."""
        try:
            stats = _calculate_project_stats(registry.client, project_id)
            return ProjectStatsResponse(**stats)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to calculate stats for project {project_id}: {e}"
            ) from e

    @router.get("/fleet/stats", response_model=FleetStatsResponse)
    async def get_fleet_stats() -> FleetStatsResponse:
        """Get fleet-wide statistics."""
        try:
            stats = _calculate_fleet_stats(registry.client)
            return FleetStatsResponse(**stats)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to calculate fleet stats: {e}"
            ) from e

    @router.get("/fleet/findings", response_model=list[FindingResponse])
    async def get_fleet_findings(
        bucket: str | None = Query(None, description="Filter by bucket (bad/ugly)"),
        severity: str | None = Query(None, description="Filter by severity (BLOCK/WARN)"),
        limit: int = Query(100, ge=1, le=1000, description="Number of findings to return"),
        offset: int = Query(0, ge=0, description="Number of findings to skip"),
    ) -> list[FindingResponse]:
        """Get findings across the fleet with optional filtering."""
        try:
            findings = _get_fleet_findings(registry.client, bucket, severity, limit, offset)
            return findings
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to retrieve fleet findings: {e}"
            ) from e

    @router.get("/fleet/invariants/{invariant_id}/findings", response_model=list[FindingResponse])
    async def get_invariant_findings(
        invariant_id: str,
        limit: int = Query(100, ge=1, le=1000, description="Number of findings to return"),
        offset: int = Query(0, ge=0, description="Number of findings to skip"),
    ) -> list[FindingResponse]:
        """Get findings for a specific invariant across the fleet."""
        try:
            findings = _get_invariant_findings(registry.client, invariant_id, limit, offset)
            return findings
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve findings for invariant {invariant_id}: {e}",
            ) from e

    @router.get("/fleet/invariants/coverage", response_model=list[InvariantCoverageResponse])
    async def get_invariant_coverage() -> list[InvariantCoverageResponse]:
        """Get invariant coverage statistics across the fleet."""
        try:
            coverage = _get_invariant_coverage(registry.client)
            return coverage
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to calculate invariant coverage: {e}"
            ) from e

    return router


def _get_all_projects_direct(client: VerdictStoreClient) -> list[ProjectRecord]:
    """Direct database query to get all projects.

    This is a temporary implementation until registry.list_projects() is available.
    """
    from verdict_store.client import ProjectRecord

    with sqlite3.connect(client.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """
            SELECT id, stonehaven_id, repo, project_name, registered_at,
                   harness_version, active
            FROM projects
            WHERE active = 1
            ORDER BY registered_at DESC
            """
        )

        projects = []
        for row in cursor.fetchall():
            from datetime import datetime

            projects.append(
                ProjectRecord(
                    id=row["id"],
                    stonehaven_id=row["stonehaven_id"],
                    repo=row["repo"],
                    project_name=row["project_name"],
                    registered_at=datetime.fromisoformat(row["registered_at"])
                    if row["registered_at"]
                    else None,
                    harness_version=row["harness_version"],
                    active=bool(row["active"]),
                )
            )
        return projects


def _calculate_project_stats(client: VerdictStoreClient, project_id: int) -> dict[str, Any]:
    """Calculate statistics for a specific project."""
    with sqlite3.connect(client.db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Get verdict counts by severity
        cursor = conn.execute(
            """
            SELECT severity, COUNT(*) as count
            FROM verdicts
            WHERE project_id = ?
            GROUP BY severity
            """,
            (project_id,),
        )

        severity_counts = {row["severity"]: row["count"] for row in cursor.fetchall()}
        block_count = severity_counts.get("BLOCK", 0)
        warn_count = severity_counts.get("WARN", 0)
        pass_count = severity_counts.get("PASS", 0)
        total_verdicts = block_count + warn_count + pass_count

        # Get average findings per PR
        cursor = conn.execute(
            """
            SELECT AVG(finding_count) as avg_findings
            FROM (
                SELECT v.pr_number, COUNT(f.id) as finding_count
                FROM verdicts v
                LEFT JOIN findings f ON v.id = f.verdict_id
                WHERE v.project_id = ?
                GROUP BY v.pr_number
            )
            """,
            (project_id,),
        )

        result = cursor.fetchone()
        avg_findings_per_pr = float(result["avg_findings"]) if result["avg_findings"] else 0.0

        return {
            "project_id": project_id,
            "total_verdicts": total_verdicts,
            "block_count": block_count,
            "warn_count": warn_count,
            "pass_count": pass_count,
            "block_rate": block_count / total_verdicts if total_verdicts > 0 else 0.0,
            "warn_rate": warn_count / total_verdicts if total_verdicts > 0 else 0.0,
            "avg_findings_per_pr": avg_findings_per_pr,
        }


def _calculate_fleet_stats(client: VerdictStoreClient) -> dict[str, Any]:
    """Calculate fleet-wide statistics."""
    with sqlite3.connect(client.db_path) as conn:
        conn.row_factory = sqlite3.Row

        # Get project counts
        cursor = conn.execute("SELECT COUNT(*) as total FROM projects")
        total_projects = cursor.fetchone()["total"]

        cursor = conn.execute("SELECT COUNT(*) as active FROM projects WHERE active = 1")
        active_projects = cursor.fetchone()["active"]

        # Get verdict counts
        cursor = conn.execute("SELECT COUNT(*) as total FROM verdicts")
        total_verdicts = cursor.fetchone()["total"]

        # Get findings count
        cursor = conn.execute("SELECT COUNT(*) as total FROM findings")
        total_findings = cursor.fetchone()["total"]

        # Calculate average rates
        cursor = conn.execute(
            """
            SELECT
                AVG(CASE WHEN severity = 'BLOCK' THEN 1.0 ELSE 0.0 END) as avg_block_rate,
                AVG(CASE WHEN severity = 'WARN' THEN 1.0 ELSE 0.0 END) as avg_warn_rate
            FROM verdicts
            """
        )

        rates = cursor.fetchone()
        avg_block_rate = float(rates["avg_block_rate"]) if rates["avg_block_rate"] else 0.0
        avg_warn_rate = float(rates["avg_warn_rate"]) if rates["avg_warn_rate"] else 0.0

        # Calculate average findings per PR
        cursor = conn.execute(
            """
            SELECT AVG(finding_count) as avg_findings
            FROM (
                SELECT v.pr_number, v.project_id, COUNT(f.id) as finding_count
                FROM verdicts v
                LEFT JOIN findings f ON v.id = f.verdict_id
                GROUP BY v.pr_number, v.project_id
            )
            """
        )

        result = cursor.fetchone()
        avg_findings_per_pr = float(result["avg_findings"]) if result["avg_findings"] else 0.0

        return {
            "total_projects": total_projects,
            "active_projects": active_projects,
            "total_verdicts": total_verdicts,
            "total_findings": total_findings,
            "avg_block_rate": avg_block_rate,
            "avg_warn_rate": avg_warn_rate,
            "avg_findings_per_pr": avg_findings_per_pr,
        }


def _get_fleet_findings(
    client: VerdictStoreClient, bucket: str | None, severity: str | None, limit: int, offset: int
) -> list[FindingResponse]:
    """Get findings across the fleet with filtering."""
    with sqlite3.connect(client.db_path) as conn:
        conn.row_factory = sqlite3.Row

        where_clauses = []
        params: list[Any] = []

        if bucket:
            where_clauses.append("f.bucket = ?")
            params.append(bucket)

        if severity:
            where_clauses.append("f.severity = ?")
            params.append(severity)

        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        query = f"""
            SELECT f.id, f.verdict_id, f.bucket, f.text, f.severity, f.invariant_id,
                   v.project_id, p.project_name, v.reviewed_at
            FROM findings f
            JOIN verdicts v ON f.verdict_id = v.id
            JOIN projects p ON v.project_id = p.id
            {where_clause}
            ORDER BY v.reviewed_at DESC
            LIMIT ? OFFSET ?
        """

        params.extend([limit, offset])
        cursor = conn.execute(query, params)

        findings = []
        for row in cursor.fetchall():
            findings.append(
                FindingResponse(
                    id=row["id"],
                    verdict_id=row["verdict_id"],
                    project_id=row["project_id"],
                    project_name=row["project_name"],
                    bucket=row["bucket"],
                    text=row["text"],
                    severity=row["severity"],
                    invariant_id=row["invariant_id"],
                    reviewed_at=row["reviewed_at"] or "",
                )
            )

        return findings


def _get_invariant_findings(
    client: VerdictStoreClient, invariant_id: str, limit: int, offset: int
) -> list[FindingResponse]:
    """Get findings for a specific invariant."""
    with sqlite3.connect(client.db_path) as conn:
        conn.row_factory = sqlite3.Row

        cursor = conn.execute(
            """
            SELECT f.id, f.verdict_id, f.bucket, f.text, f.severity, f.invariant_id,
                   v.project_id, p.project_name, v.reviewed_at
            FROM findings f
            JOIN verdicts v ON f.verdict_id = v.id
            JOIN projects p ON v.project_id = p.id
            WHERE f.invariant_id = ?
            ORDER BY v.reviewed_at DESC
            LIMIT ? OFFSET ?
            """,
            (invariant_id, limit, offset),
        )

        findings = []
        for row in cursor.fetchall():
            findings.append(
                FindingResponse(
                    id=row["id"],
                    verdict_id=row["verdict_id"],
                    project_id=row["project_id"],
                    project_name=row["project_name"],
                    bucket=row["bucket"],
                    text=row["text"],
                    severity=row["severity"],
                    invariant_id=row["invariant_id"],
                    reviewed_at=row["reviewed_at"] or "",
                )
            )

        return findings


def _get_invariant_coverage(client: VerdictStoreClient) -> list[InvariantCoverageResponse]:
    """Get invariant coverage statistics."""
    with sqlite3.connect(client.db_path) as conn:
        conn.row_factory = sqlite3.Row

        cursor = conn.execute(
            """
            SELECT
                f.invariant_id,
                COUNT(*) as total_findings,
                COUNT(DISTINCT v.project_id) as projects_affected,
                AVG(CASE
                    WHEN f.severity = 'BLOCK' THEN 2.0
                    WHEN f.severity = 'WARN' THEN 1.0
                    ELSE 0.0
                END) as avg_severity_score
            FROM findings f
            JOIN verdicts v ON f.verdict_id = v.id
            WHERE f.invariant_id IS NOT NULL
            GROUP BY f.invariant_id
            ORDER BY total_findings DESC
            """
        )

        coverage = []
        for row in cursor.fetchall():
            coverage.append(
                InvariantCoverageResponse(
                    invariant_id=row["invariant_id"],
                    total_findings=row["total_findings"],
                    projects_affected=row["projects_affected"],
                    avg_severity_score=float(row["avg_severity_score"]),
                )
            )

        return coverage


__all__ = ["create_admin_router"]
