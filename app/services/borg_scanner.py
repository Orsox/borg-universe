from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.models.borg import DEFAULT_SUPABASE_SCOPES, BorgSkill, BorgUnit


def scan_agents(settings: Settings) -> list[BorgUnit]:
    roots = [settings.agents_root, settings.borg_root / "agents"]
    units: dict[str, BorgUnit] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.md")):
            if path.name.upper() == "README.MD":
                continue
            unit = _agent_from_markdown(path)
            units[unit.name] = unit
        for manifest in sorted(root.glob("*/manifest.json")):
            unit = _unit_from_manifest(manifest)
            units[unit.name] = unit
    return list(units.values())


def scan_skills(settings: Settings) -> list[BorgSkill]:
    roots = [settings.skills_root, settings.borg_root / "skills"]
    units: dict[str, BorgSkill] = {}
    for root in roots:
        if not root.exists():
            continue
        for skill_md in sorted(root.glob("*/SKILL.md")):
            unit = _skill_from_markdown(skill_md)
            units[unit.name] = unit
        for manifest in sorted(root.glob("*/manifest.json")):
            unit = _skill_from_manifest(manifest)
            units[unit.name] = unit
    return list(units.values())


def _agent_from_markdown(path: Path) -> BorgUnit:
    metadata = _read_frontmatter(path)
    name = metadata.get("name") or path.stem
    return BorgUnit(
        name=name,
        description=metadata.get("description", ""),
        path=str(path),
        version=metadata.get("version"),
        maintainer=metadata.get("maintainer"),
        requires_supabase_project_lookup=True,
        allowed_supabase_scopes=list(DEFAULT_SUPABASE_SCOPES),
    )


def _skill_from_markdown(path: Path) -> BorgSkill:
    metadata = _read_frontmatter(path)
    name = metadata.get("name") or path.parent.name
    return BorgSkill(
        name=name,
        description=metadata.get("description", ""),
        path=str(path),
        version=metadata.get("version"),
        maintainer=metadata.get("maintainer"),
        requires_supabase_project_lookup=True,
        allowed_supabase_scopes=list(DEFAULT_SUPABASE_SCOPES),
    )


def _unit_from_manifest(path: Path) -> BorgUnit:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return BorgUnit(
        name=manifest["name"],
        description=manifest.get("description", ""),
        path=str(path),
        enabled=manifest.get("enabled", True),
        version=manifest.get("version"),
        maintainer=manifest.get("maintainer"),
        requires_supabase_project_lookup=manifest.get("requires_supabase_project_lookup", True),
        allowed_supabase_scopes=manifest.get("allowed_supabase_scopes", list(DEFAULT_SUPABASE_SCOPES)),
    )


def _skill_from_manifest(path: Path) -> BorgSkill:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return BorgSkill(
        name=manifest["name"],
        description=manifest.get("description", ""),
        path=str(path),
        enabled=manifest.get("enabled", True),
        version=manifest.get("version"),
        maintainer=manifest.get("maintainer"),
        input_schema=manifest.get("input_schema", {}),
        output_schema=manifest.get("output_schema", {}),
        requires_supabase_project_lookup=manifest.get("requires_supabase_project_lookup", True),
        allowed_supabase_scopes=manifest.get("allowed_supabase_scopes", list(DEFAULT_SUPABASE_SCOPES)),
    )


def _read_frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    return metadata
