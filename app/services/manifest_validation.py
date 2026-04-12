from __future__ import annotations

from typing import Any

from app.models.borg import DEFAULT_SUPABASE_SCOPES


class ManifestValidationError(ValueError):
    pass


def validate_borg_manifest(manifest: dict[str, Any], *, source: str) -> None:
    name = str(manifest.get("name") or "").strip()
    if not name:
        raise ManifestValidationError(f"{source}: missing required field 'name'")

    requires_lookup = manifest.get("requires_supabase_project_lookup", True)
    if requires_lookup is not True:
        raise ManifestValidationError(
            f"{source}: requires_supabase_project_lookup must be true for Borg agents and skills"
        )

    scopes = manifest.get("allowed_supabase_scopes", list(DEFAULT_SUPABASE_SCOPES))
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise ManifestValidationError(f"{source}: allowed_supabase_scopes must be a list of strings")

    allowed = set(DEFAULT_SUPABASE_SCOPES)
    unknown = sorted(set(scopes) - allowed)
    if unknown:
        raise ManifestValidationError(
            f"{source}: unsupported allowed_supabase_scopes: {', '.join(unknown)}"
        )
