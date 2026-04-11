from pydantic import BaseModel, ConfigDict, Field


def split_csv(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    return [item.strip() for item in value.split(",") if item.strip()]


class KnowledgeEntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    domain: str | None = None
    platform: str | None = None
    mcu_family: str | None = None
    peripheral: str | None = None
    content: str = Field(min_length=1)
    source: str | None = None
    quality_level: str | None = None
    tags: list[str] = Field(default_factory=list)


class KnowledgeEntry(KnowledgeEntryCreate):
    model_config = ConfigDict(extra="allow")

    id: str
    created_at: str
    updated_at: str


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    scope: str | None = None
    severity: str = "info"
    rule_text: str = Field(min_length=1)
    applies_to: list[str] = Field(default_factory=list)


class Rule(RuleCreate):
    model_config = ConfigDict(extra="allow")

    id: str
    created_at: str
    updated_at: str


class CodeExampleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    platform: str | None = None
    framework: str | None = None
    language: str | None = None
    peripheral: str | None = None
    code: str = Field(min_length=1)
    explanation: str | None = None
    known_limitations: str | None = None
    tags: list[str] = Field(default_factory=list)


class CodeExample(CodeExampleCreate):
    model_config = ConfigDict(extra="allow")

    id: str
    created_at: str
    updated_at: str
