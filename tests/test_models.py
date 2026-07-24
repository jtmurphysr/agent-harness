"""Tests for verdict_store.models module."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from verdict_store.models import create_tables, enable_wal_mode, init_database


def test_init_database_creates_all_tables():
    """Test that init_database creates all required tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        
        init_database(db_path)
        
        # Verify database file was created
        assert db_path.exists()
        
        # Verify all tables exist
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            
        expected_tables = ["findings", "projects", "verdicts"]
        assert tables == expected_tables


def test_create_tables_projects_schema():
    """Test projects table has correct schema."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            create_tables(conn)
            
            # Check table schema
            cursor = conn.execute("PRAGMA table_info(projects)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
        expected_columns = {
            "id": "INTEGER",
            "stonehaven_id": "TEXT",
            "repo": "TEXT", 
            "project_name": "TEXT",
            "registered_at": "DATETIME",
            "harness_version": "TEXT",
            "active": "BOOLEAN"
        }
        
        assert columns == expected_columns


def test_create_tables_verdicts_schema():
    """Test verdicts table has correct schema."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            create_tables(conn)
            
            # Check table schema  
            cursor = conn.execute("PRAGMA table_info(verdicts)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
        expected_columns = {
            "id": "INTEGER",
            "delivery_id": "TEXT",
            "project_id": "INTEGER",
            "pr_number": "INTEGER",
            "pr_sha": "TEXT",
            "pr_size_lines": "INTEGER",
            "reviewer": "TEXT",
            "severity": "TEXT",
            "good": "TEXT",
            "bad": "TEXT",
            "ugly": "TEXT",
            "closing_question": "TEXT",
            "raw_response": "TEXT",
            "template_version": "TEXT",
            "reviewed_at": "DATETIME"
        }
        
        assert columns == expected_columns


def test_create_tables_findings_schema():
    """Test findings table has correct schema."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            create_tables(conn)
            
            # Check table schema
            cursor = conn.execute("PRAGMA table_info(findings)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
        expected_columns = {
            "id": "INTEGER",
            "verdict_id": "INTEGER", 
            "bucket": "TEXT",
            "text": "TEXT",
            "severity": "TEXT",
            "invariant_id": "TEXT"
        }
        
        assert columns == expected_columns


def test_enable_wal_mode_sets_journal_mode():
    """Test that enable_wal_mode sets journal mode to WAL."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            enable_wal_mode(conn)
            
            # Check journal mode
            cursor = conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            
        assert journal_mode.upper() == "WAL"


def test_all_indexes_created():
    """Test that all required indexes are created."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            create_tables(conn)
            
            # Get all indexes
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
            indexes = [row[0] for row in cursor.fetchall()]
            
        expected_indexes = [
            "idx_delivery_reviewer",
            "idx_invariant", 
            "idx_pr",
            "idx_project_time",
            "idx_severity"
        ]
        
        # Sort both lists for comparison since order doesn't matter
        assert sorted(indexes) == sorted(expected_indexes)


def test_create_tables_idempotent():
    """Test that create_tables can be called multiple times safely."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            # Create tables twice - should not raise an error
            create_tables(conn)
            create_tables(conn)
            
            # Verify tables still exist and are accessible
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
        expected_tables = ["findings", "projects", "verdicts"]
        assert sorted(tables) == sorted(expected_tables)


def test_foreign_key_constraints_exist():
    """Test that foreign key constraints are properly set up."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            # Enable foreign key enforcement
            conn.execute("PRAGMA foreign_keys=ON")
            create_tables(conn)
            
            # Try to insert findings record with invalid verdict_id
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO findings (verdict_id, bucket, text, severity) "
                    "VALUES (999, 'bad', 'test finding', 'WARN')"
                )
                
            # Try to insert verdicts record with invalid project_id  
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO verdicts (delivery_id, project_id, pr_number, pr_sha, "
                    "reviewer, severity, raw_response) "
                    "VALUES ('test-delivery', 999, 1, 'abc123', 'engineer', 'PASS', 'test')"
                )


def test_unique_constraints_enforced():
    """Test that unique constraints are properly enforced."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmpfile:
        with sqlite3.connect(tmpfile.name) as conn:
            create_tables(conn)
            
            # Insert a project
            conn.execute(
                "INSERT INTO projects (stonehaven_id, repo, project_name) "
                "VALUES ('test-id-1', 'org/repo1', 'Test Project')"
            )
            
            # Try to insert duplicate stonehaven_id - should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO projects (stonehaven_id, repo, project_name) "
                    "VALUES ('test-id-1', 'org/repo2', 'Another Project')"
                )
                
            # Try to insert duplicate repo - should fail
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO projects (stonehaven_id, repo, project_name) "
                    "VALUES ('test-id-2', 'org/repo1', 'Another Project')"
                )


def test_database_path_creation():
    """Test that init_database creates parent directories if they don't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a nested path that doesn't exist yet
        db_path = Path(tmpdir) / "nested" / "subdirectory" / "test.db"
        
        init_database(db_path)
        
        # Verify the path was created and database exists
        assert db_path.exists()
        assert db_path.parent.exists()
        
        # Verify database is functional
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
        assert len(tables) == 3  # projects, verdicts, findings