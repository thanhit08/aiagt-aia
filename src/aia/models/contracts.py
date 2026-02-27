from pydantic import BaseModel, ConfigDict, Field


class FileMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1)
    content_type: str
    size_bytes: int = Field(ge=1)


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    instruction: str = Field(min_length=3, max_length=4000)
    file_meta: FileMeta


class ActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str = Field(pattern=r"^(jira|slack)$")
    action: str = Field(min_length=3, max_length=80)
    params: dict = Field(default_factory=dict)
    risk_level: str = Field(pattern=r"^(low|medium|high)$")
    depends_on: list[str] = Field(default_factory=list)


class EnrichedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(
        pattern=r"^(general_query|tool_orchestration|summarization|analysis|triage)$"
    )
    requires_rag: bool = False
    output_tone: str = Field(pattern=r"^(executive|neutral|technical)$")
    rag_query_seed: str = Field(default="", max_length=1000)
    action_plans: list[ActionPlan] = Field(default_factory=list)


class RoutePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parallel: bool = True
    action_plans: list[ActionPlan] = Field(default_factory=list)


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str = Field(pattern=r"^(jira|slack)$")
    action: str = Field(min_length=3)
    status: str = Field(pattern=r"^(success|failed|skipped)$")
    data: dict = Field(default_factory=dict)
    error: str | None = None


class FinalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    trace_id: str = Field(min_length=1, max_length=200)
    action_results: list[ActionResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

