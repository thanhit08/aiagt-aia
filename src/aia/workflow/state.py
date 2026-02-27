from typing import TypedDict


class WorkflowState(TypedDict, total=False):
    request_id: str
    user_id: str
    instruction: str
    file_id: str
    trace_id: str
    enriched_task: dict
    rag_context: dict
    answer: str
    route_plan: dict
    action_results: list[dict]
    errors: list[str]
    final_response: dict
