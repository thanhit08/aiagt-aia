from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RoutingHint(str, Enum):
    HIGH_SEVERITY_FIRST = "high_severity_first"
    DEDUPE_BEFORE_CREATE = "dedupe_before_create"
    STRICT_SCHEMA = "strict_schema"
    RISK_FOCUS = "risk_focus"


class FileMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    content_type: str = Field(
        pattern=r"^(text/csv|application/vnd\.openxmlformats-officedocument\.spreadsheetml\.sheet|text/markdown|text/plain)$"
    )
    size_bytes: int = Field(ge=1, le=5_242_880)


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    instruction: str = Field(min_length=3, max_length=4000)
    file_meta: FileMeta


class EnrichedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(pattern=r"^accuracy_filter$")
    requires_slack: bool
    requires_jira: bool
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    output_tone: str = Field(pattern=r"^(executive|neutral|technical)$")
    routing_hints: list[RoutingHint] = Field(min_length=1, max_length=10)
    rag_query_seed: str = Field(min_length=8, max_length=1000)


class ParsedIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=5000)
    steps: str = Field(min_length=1, max_length=5000)
    severity: str = Field(pattern=r"^(blocker|critical|major|minor|trivial|unknown)$")
    component: str | None = Field(default=None, max_length=120)
    environment: str | None = Field(default=None, max_length=120)


class ClassificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1, max_length=128)
    accuracy_related: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return value.strip()


class RoutePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_slack: bool
    run_jira: bool
    slack_prompt: str = Field(min_length=1, max_length=4000)
    jira_prompt: str = Field(min_length=1, max_length=4000)
    parallel: bool = True


class FinalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    summary_posted: bool
    tickets_created: int = Field(ge=0)
    duplicates_skipped: int = Field(ge=0)
    slack_url: str = Field(default="")
    jira_urls: list[str] = Field(default_factory=list)
    trace_id: str = Field(min_length=1, max_length=200)
    errors: list[str] = Field(default_factory=list)

