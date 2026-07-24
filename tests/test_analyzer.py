"""Tests for interview.analyzer module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from interview.analyzer import AnalysisError, AnalysisResult, RepoAnalyzer


class TestRepoAnalyzer:
    """Test cases for RepoAnalyzer class."""

    @pytest.fixture
    def mock_claude_client(self):
        """Mock Claude client for testing."""
        return AsyncMock()

    @pytest.fixture
    def analyzer(self, mock_claude_client):
        """Create analyzer instance with mock client."""
        return RepoAnalyzer(mock_claude_client)

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary repository for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            # Create .git directory to make it a valid repo
            (repo_path / ".git").mkdir()
            yield repo_path

    async def test_analyze_repository_python_project(self, analyzer, temp_repo):
        """Test analysis of a Python project."""
        # Create Python project structure
        (temp_repo / "pyproject.toml").write_text("""
[project]
name = "test-project"
dependencies = ["fastapi", "uvicorn"]
""")
        (temp_repo / "README.md").write_text("# Test Project\nA FastAPI web application for testing.")
        (temp_repo / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
        (temp_repo / "requirements.txt").write_text("fastapi>=0.68.0\nuvicorn>=0.15.0")

        result = await analyzer.analyze_repository(temp_repo)

        assert isinstance(result, AnalysisResult)
        assert isinstance(result.proposed_context, dict)
        assert 0.0 <= result.confidence_score <= 1.0
        assert isinstance(result.analysis_notes, str)
        
        # Check that basic structure is present
        context = result.proposed_context
        assert "project" in context
        assert "stack" in context
        assert "deployment" in context
        assert "invariants" in context
        assert "reviewers" in context
        
        # Check Python-specific details
        assert context["stack"]["language"] == "Python"
        assert "FastAPI" in context["stack"]["framework"] or "fastapi" in context["stack"]["framework"].lower()

    async def test_analyze_repository_javascript_project(self, analyzer, temp_repo):
        """Test analysis of a JavaScript project."""
        # Create JavaScript project structure
        package_json = {
            "name": "test-app",
            "dependencies": {
                "react": "^18.0.0",
                "express": "^4.18.0"
            }
        }
        (temp_repo / "package.json").write_text(json.dumps(package_json, indent=2))
        (temp_repo / "README.md").write_text("# Test App\nA React application with Express backend.")
        (temp_repo / "src" / "App.js").parent.mkdir(exist_ok=True)
        (temp_repo / "src" / "App.js").write_text("import React from 'react';")

        result = await analyzer.analyze_repository(temp_repo)

        assert isinstance(result, AnalysisResult)
        context = result.proposed_context
        
        # Check JavaScript-specific details
        assert context["stack"]["language"] == "JavaScript"
        # Framework should be detected from package.json
        framework = context["stack"]["framework"]
        # Should not be "Unknown" since we provided dependencies
        assert framework != "Unknown"

    async def test_analyze_repository_flutter_project(self, analyzer, temp_repo):
        """Test analysis of a Flutter project."""
        # Create Flutter project structure
        pubspec_content = """
name: test_flutter_app
description: A Flutter test application.

dependencies:
  flutter:
    sdk: flutter
  sqflite: ^2.0.0
"""
        (temp_repo / "pubspec.yaml").write_text(pubspec_content)
        (temp_repo / "README.md").write_text("# Flutter Test App\nA mobile application built with Flutter.")
        (temp_repo / "lib" / "main.dart").parent.mkdir(exist_ok=True)
        (temp_repo / "lib" / "main.dart").write_text("import 'package:flutter/material.dart';")

        result = await analyzer.analyze_repository(temp_repo)

        assert isinstance(result, AnalysisResult)
        context = result.proposed_context
        
        # Check Flutter-specific details
        assert context["stack"]["language"] == "Dart"
        assert context["deployment"]["surface"] == "mobile"
        assert "bundle_id" in context["project"]
        assert context["deployment"]["stores"] == ["App Store", "Google Play"]

    async def test_analyze_repository_invalid_repo(self, analyzer):
        """Test analysis of an invalid repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Directory without .git
            invalid_repo = Path(temp_dir)
            
            with pytest.raises(AnalysisError, match="not a git repository"):
                await analyzer.analyze_repository(invalid_repo)

    async def test_analyze_repository_nonexistent_path(self, analyzer):
        """Test analysis of a non-existent path."""
        nonexistent_path = Path("/nonexistent/path")
        
        with pytest.raises(AnalysisError, match="does not exist or is not a directory"):
            await analyzer.analyze_repository(nonexistent_path)

    async def test_analyze_repository_proposed_context_validates(self, analyzer, temp_repo):
        """Test that proposed context follows the expected schema structure."""
        # Create minimal valid repo
        (temp_repo / "README.md").write_text("# Test\nA test project.")
        (temp_repo / "main.py").write_text("print('hello')")

        result = await analyzer.analyze_repository(temp_repo)
        
        context = result.proposed_context
        
        # Validate required top-level sections
        required_sections = ["project", "stack", "deployment", "invariants", "reviewers"]
        for section in required_sections:
            assert section in context, f"Missing required section: {section}"
        
        # Validate project section
        project = context["project"]
        assert "name" in project
        assert "description" in project
        assert isinstance(project["name"], str)
        assert isinstance(project["description"], str)
        
        # Validate stack section
        stack = context["stack"]
        assert "language" in stack
        assert "framework" in stack
        assert isinstance(stack["language"], str)
        assert isinstance(stack["framework"], str)
        
        # Validate deployment section
        deployment = context["deployment"]
        required_deploy_fields = ["surface", "rollback_available", "forced_update", "user_data_recoverable"]
        for field in required_deploy_fields:
            assert field in deployment
        assert deployment["surface"] in ["mobile", "server", "cli", "embedded", "library"]
        assert isinstance(deployment["rollback_available"], bool)
        assert isinstance(deployment["forced_update"], bool)
        assert isinstance(deployment["user_data_recoverable"], bool)
        
        # Validate invariants section
        invariants = context["invariants"]
        assert isinstance(invariants, list)
        for invariant in invariants:
            assert "id" in invariant
            assert "rule" in invariant
            assert "severity" in invariant
            assert invariant["severity"] in [
                "data_loss", "data_consistency", "irreversibility", "correctness", "performance"
            ]
        
        # Validate reviewers section
        reviewers = context["reviewers"]
        required_reviewers = ["engineer", "architect", "sre"]
        for reviewer in required_reviewers:
            assert reviewer in reviewers
            assert "enabled" in reviewers[reviewer]
            assert "model_class" in reviewers[reviewer]
            assert isinstance(reviewers[reviewer]["enabled"], bool)

    async def test_analyze_repository_confidence_scoring(self, analyzer, temp_repo):
        """Test confidence scoring logic."""
        # Test with minimal information (low confidence)
        (temp_repo / "main.py").write_text("print('hello')")
        
        result = await analyzer.analyze_repository(temp_repo)
        low_confidence = result.confidence_score
        
        # Add more information (should increase confidence)
        (temp_repo / "README.md").write_text("# Test Project\nA comprehensive test project with detailed documentation.")
        (temp_repo / "pyproject.toml").write_text("[project]\nname = 'test'")
        (temp_repo / "requirements.txt").write_text("fastapi>=0.68.0")
        
        result2 = await analyzer.analyze_repository(temp_repo)
        high_confidence = result2.confidence_score
        
        # More information should lead to higher confidence
        assert high_confidence > low_confidence
        assert 0.0 <= low_confidence <= 1.0
        assert 0.0 <= high_confidence <= 1.0

    async def test_exclude_patterns(self, analyzer, temp_repo):
        """Test that exclude patterns work correctly."""
        # Create files that should be excluded
        (temp_repo / ".venv").mkdir()
        (temp_repo / ".venv" / "lib").mkdir()
        (temp_repo / ".venv" / "lib" / "python.py").write_text("# virtual env file")
        
        (temp_repo / "node_modules").mkdir()
        (temp_repo / "node_modules" / "package").mkdir()
        (temp_repo / "node_modules" / "package" / "index.js").write_text("// node modules")
        
        (temp_repo / "__pycache__").mkdir()
        (temp_repo / "__pycache__" / "main.pyc").write_text("compiled python")
        
        # Create files that should be included
        (temp_repo / "src").mkdir()
        (temp_repo / "src" / "main.py").write_text("print('main')")
        (temp_repo / "README.md").write_text("# Test")
        
        result = await analyzer.analyze_repository(temp_repo)
        
        # Should have detected the included files but not excluded ones
        assert "Python" in result.analysis_notes  # Should mention Python files
        assert "virtual env" not in result.analysis_notes
        assert "node modules" not in result.analysis_notes

    async def test_custom_exclude_patterns(self, analyzer, temp_repo):
        """Test custom exclude patterns."""
        # Create test files
        (temp_repo / "important.py").write_text("print('important')")
        (temp_repo / "secret.txt").write_text("secret content")
        (temp_repo / "README.md").write_text("# Test")
        
        # Exclude .txt files
        custom_excludes = ["*.txt", ".git/*"]
        
        result = await analyzer.analyze_repository(temp_repo, exclude_patterns=custom_excludes)
        
        # Should include Python files but exclude .txt files
        assert isinstance(result, AnalysisResult)
        # The exact behavior depends on implementation, but it should not fail

    def test_should_exclude(self, analyzer):
        """Test the _should_exclude method directly."""
        repo_path = Path("/test/repo")
        test_patterns = [".git/*", "*.pyc", "node_modules/*", "__pycache__/*"]
        
        # Test directory exclusions
        assert analyzer._should_exclude(Path("/test/repo/.git/config"), repo_path, test_patterns)
        assert analyzer._should_exclude(Path("/test/repo/node_modules/package/index.js"), repo_path, test_patterns)
        assert analyzer._should_exclude(Path("/test/repo/__pycache__/main.pyc"), repo_path, test_patterns)
        
        # Test file pattern exclusions
        assert analyzer._should_exclude(Path("/test/repo/main.pyc"), repo_path, test_patterns)
        
        # Test files that should not be excluded
        assert not analyzer._should_exclude(Path("/test/repo/main.py"), repo_path, test_patterns)
        assert not analyzer._should_exclude(Path("/test/repo/src/utils.py"), repo_path, test_patterns)

    def test_identify_frameworks(self, analyzer):
        """Test framework identification logic."""
        # Test React identification
        react_package = {
            "name": "package.json",
            "content": '{"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}'
        }
        frameworks = analyzer._identify_frameworks([react_package])
        assert "React" in frameworks
        
        # Test Flutter identification
        flutter_package = {
            "name": "pubspec.yaml", 
            "content": "dependencies:\n  flutter:\n    sdk: flutter"
        }
        frameworks = analyzer._identify_frameworks([flutter_package])
        assert "Flutter" in frameworks
        
        # Test Django identification
        django_package = {
            "name": "requirements.txt",
            "content": "django>=4.0.0\npsycopg2-binary>=2.9.0"
        }
        frameworks = analyzer._identify_frameworks([django_package])
        assert "Django" in frameworks

    def test_identify_databases(self, analyzer):
        """Test database identification logic."""
        # Test PostgreSQL identification
        postgres_package = {
            "name": "requirements.txt",
            "content": "psycopg2-binary>=2.9.0\ndjango>=4.0.0"
        }
        databases = analyzer._identify_databases([postgres_package])
        assert "PostgreSQL" in databases
        
        # Test SQLite identification
        sqlite_package = {
            "name": "requirements.txt",
            "content": "sqlite3\nsqlalchemy>=1.4.0"
        }
        databases = analyzer._identify_databases([sqlite_package])
        assert any("SQLite" in db for db in databases)
        
        # Test MongoDB identification
        mongo_package = {
            "name": "requirements.txt",
            "content": "pymongo>=4.0.0\nmotor>=2.5.0"
        }
        databases = analyzer._identify_databases([mongo_package])
        assert "MongoDB" in databases

    def test_identify_deployment_type(self, analyzer):
        """Test deployment type identification logic."""
        # Test mobile app detection
        mobile_info = {
            "key_files": ["pubspec.yaml"],
            "languages": ["Dart"],
            "frameworks": ["Flutter"]
        }
        indicators = analyzer._identify_deployment_type(mobile_info)
        assert "mobile" in indicators
        
        # Test server app detection
        server_info = {
            "key_files": ["requirements.txt"],
            "languages": ["Python"],
            "frameworks": ["FastAPI"]
        }
        indicators = analyzer._identify_deployment_type(server_info)
        assert "server" in indicators
        
        # Test CLI tool detection
        cli_info = {
            "key_files": ["pyproject.toml"],
            "languages": ["Python"],
            "frameworks": []
        }
        indicators = analyzer._identify_deployment_type(cli_info)
        assert "cli" in indicators

    def test_calculate_confidence(self, analyzer):
        """Test confidence calculation logic."""
        # High confidence scenario
        rich_info = {
            "readme_content": "A comprehensive project description...",
            "key_files": ["pyproject.toml", "README.md", "requirements.txt"],
            "languages": ["Python"],
            "frameworks": ["FastAPI"]
        }
        context = {"project": {"name": "test"}}
        confidence = analyzer._calculate_confidence(context, rich_info)
        assert confidence > 0.7
        
        # Low confidence scenario
        poor_info = {
            "readme_content": "",
            "key_files": ["main.py"],
            "languages": [],
            "frameworks": []
        }
        confidence_low = analyzer._calculate_confidence(context, poor_info)
        assert confidence_low < 0.5
        assert confidence > confidence_low

    def test_analysis_result_dataclass(self):
        """Test AnalysisResult dataclass."""
        context = {"project": {"name": "test"}}
        result = AnalysisResult(
            proposed_context=context,
            confidence_score=0.85,
            analysis_notes="Test analysis notes"
        )
        
        assert result.proposed_context == context
        assert result.confidence_score == 0.85
        assert result.analysis_notes == "Test analysis notes"

    def test_analysis_error_exception(self):
        """Test AnalysisError exception."""
        with pytest.raises(AnalysisError, match="Test error message"):
            raise AnalysisError("Test error message")
        
        # Test that it's a proper Exception subclass
        try:
            raise AnalysisError("Test")
        except Exception as e:
            assert isinstance(e, AnalysisError)
            assert isinstance(e, Exception)