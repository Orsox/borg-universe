from pydantic import BaseModel, ConfigDict, Field


DEFAULT_SUPABASE_SCOPES: tuple[str, ...] = (
    "project_context",
    "knowledge",
    "rules",
    "examples",
)


class BorgUnit(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    path: str
    enabled: bool = True
    version: str | None = None
    maintainer: str | None = None
    requires_supabase_project_lookup: bool = True
    allowed_supabase_scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_SUPABASE_SCOPES))


class BorgSkill(BorgUnit):
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)


class EnableUpdate(BaseModel):
    enabled: bool
