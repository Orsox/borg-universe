from __future__ import annotations

import os
from pathlib import Path
from typing import TypedDict

from app.core.config import Settings
from app.models.projects import ProjectCreate, ProjectType


class ScannedProject(TypedDict):
    id: str
    name: str
    path: str
    project_type: ProjectType
    description: str
    parent_path: str | None


def scan_drive_for_projects(root_path: Path) -> list[ScannedProject]:
    """Scans the given root path for directories that might be projects recursively."""
    if not root_path.exists() or not root_path.is_dir():
        return []

    projects: list[ScannedProject] = []
    
    # Recursively find all directories. If it has project files, we mark it as project.
    # The user wants to see all directories to choose from a checklist.
    max_depth = 3
    
    def _scan_recursive(current_path: Path, current_depth: int, parent_path: str | None = None):
        if current_depth > max_depth:
            return

        try:
            # Sort entries to have stable output
            entries = sorted(list(current_path.iterdir()), key=lambda e: e.name.lower())
            for entry in entries:
                if entry.is_dir() and not entry.name.startswith(".") and not entry.name.startswith("OLD") and entry.name != "__pycache__":
                    project = _analyze_directory(entry)
                    if project:
                        project["parent_path"] = parent_path
                        projects.append(project)
                        
                        # Continue scanning subdirectories
                        _scan_recursive(entry, current_depth + 1, str(entry))
        except PermissionError:
            pass

    _scan_recursive(root_path, 1, str(root_path))

    # De-duplicate by path
    unique_projects = {p["path"]: p for p in projects}.values()
    # No longer sorting globally here, we want to maintain some hierarchy if possible, 
    # but the UI will handle the tree. Sorting by path helps in processing.
    return sorted(list(unique_projects), key=lambda p: p["path"].lower())


def _analyze_directory(path: Path) -> ScannedProject | None:
    """Analyzes a directory to determine if it is a project and what type it is."""
    name = path.name
    project_id = name.lower().replace(" ", "-").replace("_", "-")
    
    # Default type is python if we find typical files
    project_type: ProjectType = "python"
    description = f"Project imported from {path}"

    # Check for specific files to determine type
    if (path / "requirements.txt").exists() or (path / "setup.py").exists() or (path / "pyproject.toml").exists():
        project_type = "python"
    elif (path / "CMakeLists.txt").exists() or (path / "Makefile").exists():
        # Could be STM or Nordic, we'll stick to a guess or default
        if any(path.glob("*.ioc")): # STM32 CubeMX file
            project_type = "stm"
        else:
            project_type = "nordic"
    
    # If there's a borg-cube.md, we might find a better name/description
    cube_md = path / "borg-cube.md"
    if cube_md.exists():
        try:
            content = cube_md.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            if lines and lines[0].startswith("# "):
                name = lines[0][2:].strip()
        except Exception:
            pass

    return {
        "id": project_id,
        "name": name,
        "path": str(path),
        "project_type": project_type,
        "description": description,
        "parent_path": None
    }
