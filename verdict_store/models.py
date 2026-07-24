"""SQLite schema and table creation for verdict storage.

This module defines the database schema for the triumvirate review subsystem:
- projects: registered repositories with webhook configuration
- verdicts: review outcomes from Engineer, Architect, SRE reviewers
- findings: normalized discrete findings extracted from verdict text

All tables use SQLite with WAL mode for better concurrency under webhook load.
"""

import sqlite3
from pathlib import Path
from typing import Final

# SQL schema definitions
_CREATE_PROJECTS_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY,
    stonehaven_id   TEXT UNIQUE NOT NULL,
    repo            TEXT UNIQUE NOT NULL,       -- org/name
    project_name    TEXT NOT NULL,
    registered_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    harness_version TEXT,
    active          BOOLEAN NOT NULL DEFAULT TRUE
)
"""

_CREATE_VERDICTS_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS verdicts (
    id               INTEGER PRIMARY KEY,
    delivery_id      TEXT NOT NULL,
    project_id       INTEGER NOT NULL REFERENCES projects(id),
    pr_number        INTEGER NOT NULL,
    pr_sha           TEXT NOT NULL,
    pr_size_lines    INTEGER,                   -- from GitHub PR metadata
    reviewer         TEXT NOT NULL,             -- engineer | architect | sre
    severity         TEXT NOT NULL,             -- BLOCK | WARN | PASS
    good             TEXT,
    bad              TEXT,
    ugly             TEXT,
    closing_question TEXT,
    raw_response     TEXT NOT NULL,
    template_version TEXT,                      -- template version snapshot at review time
    reviewed_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(delivery_id, reviewer)
)
"""

_CREATE_FINDINGS_TABLE: Final[str] = """
CREATE TABLE IF NOT EXISTS findings (
    id           INTEGER PRIMARY KEY,
    verdict_id   INTEGER NOT NULL REFERENCES verdicts(id),
    bucket       TEXT NOT NULL,                 -- bad | ugly
    text         TEXT NOT NULL,
    severity     TEXT NOT NULL,                 -- BLOCK | WARN
    invariant_id TEXT                           -- nullable; populated when reviewer cites a declared invariant
)
"""

# Index creation statements
_CREATE_INDEXES: Final[tuple[str, ...]] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_reviewer ON verdicts(delivery_id, reviewer)",
    "CREATE INDEX IF NOT EXISTS idx_pr ON verdicts(project_id, pr_number)",
    "CREATE INDEX IF NOT EXISTS idx_project_time ON verdicts(project_id, reviewed_at)",
    "CREATE INDEX IF NOT EXISTS idx_severity ON verdicts(severity, reviewed_at)",
    "CREATE INDEX IF NOT EXISTS idx_invariant ON findings(invariant_id) WHERE invariant_id IS NOT NULL",
)


def init_database(db_path: Path) -> None:
    """Initialize SQLite database with all tables and indexes.

    Creates the database file if it doesn't exist, sets up all required tables
    and indexes, and enables WAL mode for better concurrency.

    Args:
        db_path: Path to the SQLite database file to create/initialize

    Raises:
        sqlite3.Error: If database initialization fails
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        create_tables(conn)
        enable_wal_mode(conn)


def create_tables(conn: sqlite3.Connection) -> None:
    """Create projects, verdicts, and findings tables.

    Creates all three core tables in dependency order and adds all required indexes.
    This function is idempotent - it's safe to call on an existing database.

    Args:
        conn: Active SQLite database connection

    Raises:
        sqlite3.Error: If table creation fails
    """
    # Create tables in dependency order: projects first, then verdicts, then findings
    conn.execute(_CREATE_PROJECTS_TABLE)
    conn.execute(_CREATE_VERDICTS_TABLE)
    conn.execute(_CREATE_FINDINGS_TABLE)

    # Create all indexes
    for index_sql in _CREATE_INDEXES:
        conn.execute(index_sql)

    conn.commit()


def enable_wal_mode(conn: sqlite3.Connection) -> None:
    """Enable WAL mode for better concurrency.

    Sets the database journal mode to WAL (Write-Ahead Logging) which allows
    concurrent reads while writes are happening. This is critical for handling
    webhook traffic where multiple reviewers may write verdicts simultaneously.

    Args:
        conn: Active SQLite database connection

    Raises:
        sqlite3.Error: If WAL mode cannot be enabled
    """
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
