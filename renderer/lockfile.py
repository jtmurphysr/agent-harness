"""Templates lock file management.

Handles reading, writing, and updating of templates_lock.yml files that track
template versions for projects. Ensures atomic file operations to prevent corruption.
"""

import tempfile
from pathlib import Path

import yaml

__all__ = ["read_lock", "update_template_version", "write_lock"]


def read_lock(lock_path: Path) -> dict[str, str]:
    """Read templates_lock.yml and return template name -> version mapping.

    Args:
        lock_path: Path to the templates_lock.yml file

    Returns:
        Dict mapping template names to their versions. Empty dict if file doesn't exist.
    """
    try:
        with open(lock_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data or {}
    except FileNotFoundError:
        return {}


def write_lock(lock_path: Path, versions: dict[str, str]) -> None:
    """Write template versions to templates_lock.yml.

    Uses atomic write pattern - writes to temp file then moves to prevent corruption.

    Args:
        lock_path: Path to the templates_lock.yml file
        versions: Dict mapping template names to their versions
    """
    # Ensure parent directory exists
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temporary file in same directory
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=lock_path.parent, delete=False, suffix=".tmp"
    ) as temp_file:
        yaml.safe_dump(versions, temp_file, default_flow_style=False, sort_keys=True)
        temp_path = Path(temp_file.name)

    # Atomic move to final location
    temp_path.replace(lock_path)


def update_template_version(lock_path: Path, template_name: str, version: str) -> None:
    """Update single template version in lock file.

    Args:
        lock_path: Path to the templates_lock.yml file
        template_name: Name of the template to update
        version: New version to set
    """
    versions = read_lock(lock_path)
    versions[template_name] = version
    write_lock(lock_path, versions)
