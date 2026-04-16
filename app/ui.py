from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.templating import Jinja2Templates


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def csv_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "")


def pretty_name(value: Any) -> str:
    return str(value or "").replace("_", " ").replace("-", " ").title()


def badge_class(value: Any) -> str:
    normalized = str(value or "").lower().replace(" ", "_")
    if normalized in {"queued", "running"}:
        return "queued"
    if normalized in {"review_required", "needs_input", "failed", "false"}:
        return "review_required"
    if normalized in {"defined", "done", "enabled", "true", "success"}:
        return "done"
    if normalized in {"disabled", "cancelled"}:
        return "disabled"
    return ""


templates.env.filters["csv"] = csv_value
templates.env.filters["pretty"] = pretty_name
templates.env.filters["badge_class"] = badge_class
