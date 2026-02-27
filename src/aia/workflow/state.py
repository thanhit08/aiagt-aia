from typing import TypedDict


class WorkflowState(TypedDict, total=False):
    request_id: str
    trace_id: str
    instruction: str
    parsed_issues: list[dict]
    enriched_task: dict
    rag_context: dict
    classified_issues: list[dict]
    accuracy_issues: list[dict]
    route_plan: dict
    slack_result: dict
    jira_result: dict
    errors: list[str]
    final_response: dict

