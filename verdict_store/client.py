"""Database client for verdict store operations.

This module provides the VerdictStoreClient class and supporting data classes
for all database read/write operations. It is the ONLY module that directly
accesses the SQLite database - all other modules must use this interface.

⚠️ WARNING: Verdict Store write ordering — Verdict Store write must succeed before GitHub issue creation
⚠️ WARNING: This is the ONLY module that touches the database — No direct DB access elsewhere
⚠️ WARNING: Transaction safety — All multi-table writes must be atomic
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import init_database


@dataclass
class ProjectRecord:
    """Project registration record."""

    id: int | None = None
    stonehaven_id: str = ""
    repo: str = ""
    project_name: str = ""
    registered_at: datetime | None = None
    harness_version: str | None = None
    active: bool = True


@dataclass
class VerdictRecord:
    """Verdict record from a reviewer."""

    id: int | None = None
    delivery_id: str = ""
    project_id: int = 0
    pr_number: int = 0
    pr_sha: str = ""
    pr_size_lines: int | None = None
    reviewer: str = ""
    severity: str = ""
    good: str | None = None
    bad: str | None = None
    ugly: str | None = None
    closing_question: str | None = None
    raw_response: str = ""
    template_version: str | None = None
    reviewed_at: datetime | None = None


@dataclass
class FindingRecord:
    """Individual finding extracted from verdict text."""

    id: int | None = None
    verdict_id: int = 0
    bucket: str = ""  # bad | ugly
    text: str = ""
    severity: str = ""  # BLOCK | WARN
    invariant_id: str | None = None


class VerdictStoreClient:
    """Client for verdict store database operations.

    This is the sole interface for database access. Provides CRUD operations
    for projects, verdicts, and findings with proper transaction safety.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize client with database path.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        init_database(db_path)

    def create_project(self, stonehaven_id: str, repo: str, project_name: str) -> int:
        """Create a new project record.

        Args:
            stonehaven_id: Unique identifier for Stonehaven registration
            repo: Repository name in org/name format
            project_name: Human-readable project name

        Returns:
            The ID of the created project record

        Raises:
            sqlite3.IntegrityError: If repo already exists
            sqlite3.Error: If database operation fails
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO projects (stonehaven_id, repo, project_name)
                VALUES (?, ?, ?)
                """,
                (stonehaven_id, repo, project_name),
            )
            if cursor.lastrowid is None:
                raise sqlite3.Error("Failed to create project record")
            return cursor.lastrowid

    def get_project_by_repo(self, repo: str) -> ProjectRecord | None:
        """Get project record by repository name.

        Args:
            repo: Repository name in org/name format

        Returns:
            ProjectRecord if found, None otherwise

        Raises:
            sqlite3.Error: If database operation fails
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, stonehaven_id, repo, project_name, registered_at,
                       harness_version, active
                FROM projects
                WHERE repo = ?
                """,
                (repo,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return ProjectRecord(
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

    def write_verdict(self, verdict: VerdictRecord) -> int:
        """Write a verdict record to the database.

        Args:
            verdict: Verdict record to write

        Returns:
            The ID of the created verdict record

        Raises:
            sqlite3.IntegrityError: If (delivery_id, reviewer) already exists
            sqlite3.Error: If database operation fails
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO verdicts (
                    delivery_id, project_id, pr_number, pr_sha, pr_size_lines,
                    reviewer, severity, good, bad, ugly, closing_question,
                    raw_response, template_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verdict.delivery_id,
                    verdict.project_id,
                    verdict.pr_number,
                    verdict.pr_sha,
                    verdict.pr_size_lines,
                    verdict.reviewer,
                    verdict.severity,
                    verdict.good,
                    verdict.bad,
                    verdict.ugly,
                    verdict.closing_question,
                    verdict.raw_response,
                    verdict.template_version,
                ),
            )
            if cursor.lastrowid is None:
                raise sqlite3.Error("Failed to create verdict record")
            return cursor.lastrowid

    def write_findings(self, verdict_id: int, findings: list[FindingRecord]) -> None:
        """Write findings for a verdict in a single transaction.

        Args:
            verdict_id: ID of the verdict these findings belong to
            findings: List of findings to write

        Raises:
            sqlite3.Error: If database operation fails
        """
        if not findings:
            return

        with sqlite3.connect(self.db_path) as conn, conn:
            # This ensures transaction is rolled back on exception
            conn.executemany(
                """
                INSERT INTO findings (verdict_id, bucket, text, severity, invariant_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        verdict_id,
                        finding.bucket,
                        finding.text,
                        finding.severity,
                        finding.invariant_id,
                    )
                    for finding in findings
                ],
            )

    def get_project_by_id(self, project_id: int) -> ProjectRecord | None:
        """Get project record by ID.

        Args:
            project_id: Project ID to look up

        Returns:
            ProjectRecord if found, None otherwise

        Raises:
            sqlite3.Error: If database operation fails
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, stonehaven_id, repo, project_name, registered_at,
                       harness_version, active
                FROM projects
                WHERE id = ?
                """,
                (project_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return ProjectRecord(
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

    def get_verdicts_for_project(
        self, project_id: int, limit: int = 100, offset: int = 0
    ) -> list[VerdictRecord]:
        """Get verdicts for a project with pagination.

        Args:
            project_id: Project ID to get verdicts for
            limit: Maximum number of verdicts to return
            offset: Number of verdicts to skip

        Returns:
            List of verdict records, most recent first

        Raises:
            sqlite3.Error: If database operation fails
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, delivery_id, project_id, pr_number, pr_sha, pr_size_lines,
                       reviewer, severity, good, bad, ugly, closing_question,
                       raw_response, template_version, reviewed_at
                FROM verdicts
                WHERE project_id = ?
                ORDER BY reviewed_at DESC
                LIMIT ? OFFSET ?
                """,
                (project_id, limit, offset),
            )

            verdicts = []
            for row in cursor.fetchall():
                verdicts.append(
                    VerdictRecord(
                        id=row["id"],
                        delivery_id=row["delivery_id"],
                        project_id=row["project_id"],
                        pr_number=row["pr_number"],
                        pr_sha=row["pr_sha"],
                        pr_size_lines=row["pr_size_lines"],
                        reviewer=row["reviewer"],
                        severity=row["severity"],
                        good=row["good"],
                        bad=row["bad"],
                        ugly=row["ugly"],
                        closing_question=row["closing_question"],
                        raw_response=row["raw_response"],
                        template_version=row["template_version"],
                        reviewed_at=datetime.fromisoformat(row["reviewed_at"])
                        if row["reviewed_at"]
                        else None,
                    )
                )
            return verdicts

    def get_findings_for_verdict(self, verdict_id: int) -> list[FindingRecord]:
        """Get all findings for a specific verdict.

        Args:
            verdict_id: Verdict ID to get findings for

        Returns:
            List of finding records

        Raises:
            sqlite3.Error: If database operation fails
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT id, verdict_id, bucket, text, severity, invariant_id
                FROM findings
                WHERE verdict_id = ?
                ORDER BY id
                """,
                (verdict_id,),
            )

            findings = []
            for row in cursor.fetchall():
                findings.append(
                    FindingRecord(
                        id=row["id"],
                        verdict_id=row["verdict_id"],
                        bucket=row["bucket"],
                        text=row["text"],
                        severity=row["severity"],
                        invariant_id=row["invariant_id"],
                    )
                )
            return findings


__all__ = ["FindingRecord", "ProjectRecord", "VerdictRecord", "VerdictStoreClient"]
