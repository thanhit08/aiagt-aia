from typing import TypedDict


class WorkflowState(TypedDict, total=False):
    request_id: str
    user_id: str
    telegram_chat_id: str
    instruction: str
    raw_instruction: str
    file_id: str
    trace_id: str
    rag_required: bool
    rag_query_spec: dict
    rag_compiled_context: str
    enriched_task: dict
    rag_context: dict
    answer: str
    route_plan: dict
    action_results: list[dict]
    errors: list[str]
    final_response: dict
