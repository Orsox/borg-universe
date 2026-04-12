from __future__ import annotations

import json
from dataclasses import replace

import pytest

from app.core.config import get_settings
from app.services.borg_scanner import scan_agents, scan_skills
from app.services.manifest_validation import ManifestValidationError, validate_borg_manifest


def test_manifest_requires_supabase_lookup() -> None:
    with pytest.raises(ManifestValidationError, match="requires_supabase_project_lookup"):
        validate_borg_manifest(
            {
                "name": "unsafe-agent",
                "requires_supabase_project_lookup": False,
                "allowed_supabase_scopes": ["knowledge"],
            },
            source="manifest.json",
        )


def test_manifest_rejects_unknown_supabase_scope() -> None:
    with pytest.raises(ManifestValidationError, match="unsupported"):
        validate_borg_manifest(
            {
                "name": "unsafe-skill",
                "requires_supabase_project_lookup": True,
                "allowed_supabase_scopes": ["knowledge", "secrets"],
            },
            source="manifest.json",
        )


def test_scanner_loads_manifest_with_required_lookup(tmp_path) -> None:
    agents_root = tmp_path / "agents"
    agent_dir = agents_root / "agent-one"
    agent_dir.mkdir(parents=True)
    (agent_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "agent-one",
                "description": "Safe agent",
                "requires_supabase_project_lookup": True,
                "allowed_supabase_scopes": ["project_context", "knowledge"],
            }
        ),
        encoding="utf-8",
    )
    settings = replace(get_settings(), agents_root=agents_root, borg_root=tmp_path / "borg")

    agents = scan_agents(settings)

    assert agents[0].name == "agent-one"
    assert agents[0].requires_supabase_project_lookup is True


def test_scanner_defaults_markdown_skills_to_required_lookup(tmp_path) -> None:
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "skill-one"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: skill-one\ndescription: Safe skill\n---\n\nBody\n",
        encoding="utf-8",
    )
    settings = replace(get_settings(), skills_root=skills_root, borg_root=tmp_path / "borg")

    skills = scan_skills(settings)

    assert skills[0].name == "skill-one"
    assert skills[0].requires_supabase_project_lookup is True
