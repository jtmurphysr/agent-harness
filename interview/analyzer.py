"""Claude Code-driven repository analysis for project context generation."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["AnalysisError", "AnalysisResult", "RepoAnalyzer"]


class AnalysisError(Exception):
    """Raised when repo analysis fails."""


@dataclass
class AnalysisResult:
    """Result of repository analysis."""

    proposed_context: dict[str, Any]
    confidence_score: float
    analysis_notes: str


class RepoAnalyzer:
    """Repository analyzer using Claude Code for intelligent project context generation."""

    def __init__(self, claude_client: Any) -> None:
        """Initialize the analyzer.

        Args:
            claude_client: Claude client instance for API calls
        """
        self.claude_client = claude_client

    async def analyze_repository(
        self, repo_path: Path, exclude_patterns: list[str] | None = None
    ) -> AnalysisResult:
        """Analyze a repository to generate proposed project context.

        Args:
            repo_path: Path to the repository root
            exclude_patterns: Optional glob patterns to exclude from analysis

        Returns:
            AnalysisResult with proposed context and confidence score

        Raises:
            AnalysisError: If analysis fails or repo is invalid
        """
        if exclude_patterns is None:
            exclude_patterns = [
                ".git/*",
                "node_modules/*",
                ".venv/*",
                "venv/*",
                "__pycache__/*",
                "*.pyc",
                ".DS_Store",
                "*.log",
                "build/*",
                "dist/*",
                ".idea/*",
                ".vscode/*",
            ]

        if not repo_path.exists() or not repo_path.is_dir():
            raise AnalysisError(
                f"Repository path does not exist or is not a directory: {repo_path}"
            )

        # Check if it's a git repository
        if not (repo_path / ".git").exists():
            raise AnalysisError(f"Path is not a git repository (no .git directory): {repo_path}")

        try:
            # Gather repository information
            repo_info = await self._gather_repo_info(repo_path, exclude_patterns)

            # Analyze with Claude Code
            context_data = await self._analyze_with_claude(repo_info, repo_path)

            # Calculate confidence score
            confidence = self._calculate_confidence(context_data, repo_info)

            # Generate analysis notes
            notes = self._generate_analysis_notes(repo_info, confidence)

            return AnalysisResult(
                proposed_context=context_data, confidence_score=confidence, analysis_notes=notes
            )

        except Exception as e:
            raise AnalysisError(f"Analysis failed: {e}") from e

    async def _gather_repo_info(
        self, repo_path: Path, exclude_patterns: list[str]
    ) -> dict[str, Any]:
        """Gather basic information about the repository structure."""
        info: dict[str, Any] = {
            "repo_name": repo_path.name,
            "file_counts": {},
            "key_files": [],
            "languages": [],
            "frameworks": [],
            "databases": [],
            "deployment_indicators": [],
            "readme_content": "",
            "package_files": [],
        }

        # Count files by extension and identify key files
        for file_path in repo_path.rglob("*"):
            if file_path.is_file() and not self._should_exclude(
                file_path, repo_path, exclude_patterns
            ):
                ext = file_path.suffix.lower()
                info["file_counts"][ext] = info["file_counts"].get(ext, 0) + 1

                # Identify key configuration and project files
                filename = file_path.name.lower()
                if filename in [
                    "package.json",
                    "pyproject.toml",
                    "cargo.toml",
                    "pom.xml",
                    "pubspec.yaml",
                    "build.gradle",
                    "requirements.txt",
                    "dockerfile",
                    "docker-compose.yml",
                    "readme.md",
                    "readme.rst",
                    "readme.txt",
                    ".gitignore",
                    "makefile",
                    "gemfile",
                    "composer.json",
                ]:
                    info["key_files"].append(str(file_path.relative_to(repo_path)))

                    # Try to read package files for dependency analysis
                    if filename in [
                        "package.json",
                        "pyproject.toml",
                        "pubspec.yaml",
                        "requirements.txt",
                    ]:
                        try:
                            content = file_path.read_text(encoding="utf-8")[:5000]  # Limit size
                            info["package_files"].append({"name": filename, "content": content})
                        except (OSError, UnicodeDecodeError):
                            pass  # Skip files we can't read

                # Read README for project description
                if filename.startswith("readme"):
                    try:
                        content = file_path.read_text(encoding="utf-8")[:3000]  # Limit size
                        info["readme_content"] = content
                    except (OSError, UnicodeDecodeError):
                        pass

        # Identify languages by file extensions
        language_mappings = {
            ".py": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".dart": "Dart",
            ".java": "Java",
            ".kt": "Kotlin",
            ".swift": "Swift",
            ".go": "Go",
            ".rs": "Rust",
            ".php": "PHP",
            ".rb": "Ruby",
            ".c": "C",
            ".cpp": "C++",
            ".cs": "C#",
            ".scala": "Scala",
        }

        file_counts: dict[str, int] = info["file_counts"]
        languages: list[str] = info["languages"]
        for ext, count in file_counts.items():
            if ext in language_mappings and count > 0:
                languages.append(language_mappings[ext])

        # Identify frameworks and databases based on package files
        info["frameworks"] = self._identify_frameworks(info["package_files"])
        info["databases"] = self._identify_databases(info["package_files"])
        info["deployment_indicators"] = self._identify_deployment_type(info)

        return info

    def _should_exclude(
        self, file_path: Path, repo_path: Path, exclude_patterns: list[str]
    ) -> bool:
        """Check if a file should be excluded based on patterns."""
        relative_path = str(file_path.relative_to(repo_path))

        for pattern in exclude_patterns:
            # Simple glob-style matching
            if pattern.endswith("/*"):
                dir_pattern = pattern[:-2]
                if relative_path.startswith(dir_pattern + "/") or relative_path == dir_pattern:
                    return True
            elif "*" in pattern:
                # Basic wildcard matching
                regex_pattern = pattern.replace("*", ".*")
                if re.match(regex_pattern, relative_path):
                    return True
            elif relative_path == pattern or relative_path.endswith("/" + pattern):
                return True

        return False

    def _identify_frameworks(self, package_files: list[dict[str, str]]) -> list[str]:
        """Identify frameworks from package file contents."""
        frameworks = []

        for pkg_file in package_files:
            content = pkg_file["content"].lower()

            # JavaScript/TypeScript frameworks
            if "react" in content:
                frameworks.append("React")
            if "angular" in content:
                frameworks.append("Angular")
            if "vue" in content:
                frameworks.append("Vue.js")
            if "express" in content:
                frameworks.append("Express")
            if "nestjs" in content:
                frameworks.append("NestJS")

            # Python frameworks
            if "django" in content:
                frameworks.append("Django")
            if "flask" in content:
                frameworks.append("Flask")
            if "fastapi" in content:
                frameworks.append("FastAPI")

            # Mobile frameworks
            if "flutter" in content or pkg_file["name"] == "pubspec.yaml":
                frameworks.append("Flutter")

        return list(set(frameworks))  # Remove duplicates

    def _identify_databases(self, package_files: list[dict[str, str]]) -> list[str]:
        """Identify databases from package file contents."""
        databases = []

        for pkg_file in package_files:
            content = pkg_file["content"].lower()

            # SQL databases
            if "postgresql" in content or "psycopg" in content:
                databases.append("PostgreSQL")
            if "mysql" in content:
                databases.append("MySQL")
            if "sqlite" in content:
                databases.append("SQLite")

            # NoSQL databases
            if "mongodb" in content or "pymongo" in content:
                databases.append("MongoDB")
            if "redis" in content:
                databases.append("Redis")

            # ORMs that indicate database usage
            if "sqlalchemy" in content:
                databases.append("SQLAlchemy ORM")
            if "django" in content:
                databases.append("Django ORM")
            if "drift" in content:
                databases.append("SQLite with Drift ORM")

        return list(set(databases))

    def _identify_deployment_type(self, repo_info: dict[str, Any]) -> list[str]:
        """Identify deployment surface indicators."""
        indicators = []

        # Mobile apps
        if "pubspec.yaml" in repo_info["key_files"]:
            indicators.append("mobile")
        if any(lang in repo_info["languages"] for lang in ["Swift", "Kotlin"]):
            indicators.append("mobile")

        # Web applications
        if "package.json" in repo_info["key_files"] and any(
            fw in repo_info["frameworks"] for fw in ["React", "Angular", "Vue.js"]
        ):
            indicators.append("web")

        # CLI tools
        if "pyproject.toml" in repo_info["key_files"] or "cargo.toml" in repo_info["key_files"]:
            indicators.append("cli")

        # Server applications
        if any(
            fw in repo_info["frameworks"]
            for fw in ["Django", "Flask", "FastAPI", "Express", "NestJS"]
        ):
            indicators.append("server")

        # Docker deployment
        if "dockerfile" in repo_info["key_files"] or "docker-compose.yml" in repo_info["key_files"]:
            indicators.append("containerized")

        return indicators

    async def _analyze_with_claude(
        self, repo_info: dict[str, Any], repo_path: Path
    ) -> dict[str, Any]:
        """Use Claude Code to analyze the repository and generate project context."""
        # This is a simplified mock implementation for the interface
        # In a real implementation, this would call the Claude API with a structured prompt
        # For now, we'll generate a reasonable default based on repo_info
        return self._generate_default_context(repo_info, repo_path)

    def _generate_default_context(
        self, repo_info: dict[str, Any], repo_path: Path
    ) -> dict[str, Any]:
        """Generate a default project context based on repository analysis."""
        # Determine primary language and framework
        primary_language = "Python"  # Default
        languages: list[str] = repo_info["languages"]
        if languages:
            # Use the most common language based on file extensions
            lang_counts: dict[str, int] = {}
            for lang in languages:
                # Simple heuristic: count occurrences
                lang_counts[lang] = languages.count(lang)
            primary_language = (
                max(lang_counts.keys(), key=lambda x: lang_counts[x]) if lang_counts else "Python"
            )

        primary_framework = "Unknown"
        frameworks: list[str] = repo_info["frameworks"]
        if frameworks:
            primary_framework = frameworks[0]

        # Determine deployment surface
        deployment_surface = "cli"
        if "mobile" in repo_info["deployment_indicators"]:
            deployment_surface = "mobile"
        elif (
            "web" in repo_info["deployment_indicators"]
            or "server" in repo_info["deployment_indicators"]
            or "containerized" in repo_info["deployment_indicators"]
        ):
            deployment_surface = "server"

        # Generate bundle_id for mobile apps
        bundle_id = None
        if deployment_surface == "mobile":
            # Create a reverse domain name
            clean_name = re.sub(r"[^a-zA-Z0-9]", "", repo_path.name.lower())
            bundle_id = f"com.example.{clean_name}"

        # Determine database
        database = None
        databases: list[str] = repo_info["databases"]
        if databases:
            database = databases[0]

        # Generate high blast radius files based on common patterns
        high_blast_radius: list[str] = []
        generated_files: list[str] = []

        key_files: list[str] = repo_info["key_files"]
        for key_file in key_files:
            if key_file in ["package.json", "pyproject.toml", "pubspec.yaml"]:
                high_blast_radius.append(key_file)
            if key_file.endswith(".g.dart") or key_file.endswith(".generated.py"):
                generated_files.append(key_file)

        # Project description from README or default
        description = "A software project"
        if repo_info["readme_content"]:
            # Extract first paragraph or first few lines
            lines = repo_info["readme_content"].split("\n")
            non_empty_lines = [
                line.strip() for line in lines if line.strip() and not line.startswith("#")
            ]
            if non_empty_lines:
                description = non_empty_lines[0][:200] + (
                    "..." if len(non_empty_lines[0]) > 200 else ""
                )

        # Generate context structure
        context = {
            "project": {
                "name": repo_path.name.replace("-", " ").replace("_", " ").title(),
                "description": description,
            },
            "stack": {
                "language": primary_language,
                "framework": primary_framework,
            },
            "deployment": {
                "surface": deployment_surface,
                "rollback_available": deployment_surface != "mobile",
                "forced_update": False,
                "user_data_recoverable": deployment_surface == "server",
            },
            "invariants": [
                {
                    "id": "input_validation",
                    "rule": "All user inputs must be validated before processing",
                    "severity": "correctness",
                }
            ],
            "sharp_edges": [],
            "structural_decisions": [
                {
                    "decision": f"Use {primary_framework} as the primary framework",
                    "rationale": f"Standard choice for {primary_language} projects",
                }
            ],
            "becoming": [
                "Improve test coverage",
                "Add comprehensive logging",
                "Optimize performance",
            ],
            "reviewers": {
                "engineer": {"enabled": True, "model_class": "code_review"},
                "architect": {"enabled": True, "model_class": "structural_review"},
                "sre": {"enabled": True, "model_class": "adversarial_review"},
                "deploy": {
                    "enabled": deployment_surface in ["mobile", "server"],
                    "surfaces": [deployment_surface]
                    if deployment_surface in ["mobile", "server"]
                    else [],
                },
            },
        }

        # Add optional fields if they exist
        project_section = context["project"]
        stack_section = context["stack"]
        deployment_section = context["deployment"]

        if bundle_id:
            assert isinstance(project_section, dict)
            project_section["bundle_id"] = bundle_id

        if database:
            assert isinstance(stack_section, dict)
            stack_section["database"] = database

        if high_blast_radius or generated_files:
            primary_files: dict[str, list[str]] = {}
            if high_blast_radius:
                primary_files["high_blast_radius"] = high_blast_radius
            if generated_files:
                primary_files["generated"] = generated_files
            assert isinstance(stack_section, dict)
            stack_section["primary_files"] = primary_files

        if deployment_surface == "mobile":
            assert isinstance(deployment_section, dict)
            deployment_section["stores"] = ["App Store", "Google Play"]

        # Add framework-specific invariants and sharp edges
        invariants_obj = context["invariants"]
        sharp_edges_obj = context["sharp_edges"]
        assert isinstance(invariants_obj, list)
        assert isinstance(sharp_edges_obj, list)
        invariants: list[dict[str, str]] = invariants_obj
        sharp_edges: list[dict[str, str]] = sharp_edges_obj

        if primary_framework == "Flutter":
            invariants.extend(
                [
                    {
                        "id": "async_ui_updates",
                        "rule": "UI updates must be performed on the main thread",
                        "severity": "correctness",
                    }
                ]
            )
            sharp_edges.extend(
                [
                    {
                        "location": "generated files",
                        "issue": "Generated files should not be manually edited",
                        "fix": "Re-run code generation after schema changes",
                    }
                ]
            )
        elif primary_framework in ["Django", "FastAPI", "Flask"]:
            invariants.extend(
                [
                    {
                        "id": "sql_injection_prevention",
                        "rule": "All database queries must use parameterized statements",
                        "severity": "data_consistency",
                    }
                ]
            )

        return context

    def _calculate_confidence(
        self, context_data: dict[str, Any], repo_info: dict[str, Any]
    ) -> float:
        """Calculate confidence score for the analysis."""
        confidence = 0.5  # Base confidence

        # Increase confidence based on available information
        if repo_info["readme_content"]:
            confidence += 0.2

        if repo_info["key_files"]:
            confidence += 0.1

        if repo_info["languages"]:
            confidence += 0.1

        if repo_info["frameworks"]:
            confidence += 0.1

        # Decrease confidence if too little information
        if len(repo_info["key_files"]) < 2:
            confidence -= 0.1

        if not repo_info["readme_content"]:
            confidence -= 0.1

        # Ensure confidence is between 0 and 1
        return max(0.0, min(1.0, confidence))

    def _generate_analysis_notes(self, repo_info: dict[str, Any], confidence: float) -> str:
        """Generate human-readable analysis notes."""
        notes = [
            "Repository Analysis Summary:",
            f"- Detected {len(repo_info['languages'])} programming languages: {', '.join(repo_info['languages'])}",
            f"- Found {len(repo_info['frameworks'])} frameworks: {', '.join(repo_info['frameworks'])}",
            f"- Identified {len(repo_info['key_files'])} key configuration files",
        ]

        if repo_info["databases"]:
            notes.append(f"- Database technologies: {', '.join(repo_info['databases'])}")

        notes.append(f"- Deployment indicators: {', '.join(repo_info['deployment_indicators'])}")
        notes.append(f"- Analysis confidence: {confidence:.2f}")

        if confidence < 0.6:
            notes.append("")
            notes.append("⚠️ Low confidence score. Consider:")
            notes.append("  - Adding a more detailed README")
            notes.append("  - Including more configuration files")
            notes.append("  - Manually reviewing and editing the proposed context")

        return "\n".join(notes)
