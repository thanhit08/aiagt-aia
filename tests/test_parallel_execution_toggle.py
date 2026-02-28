import time

from aia.workflow.nodes import NodeDeps, execute_actions_node


class _DummyLLM:
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        return {}

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        return "ok"


class _DummyVector:
    def upsert_chunks(self, *, file_id: str, chunks: list[str]):
        return {"status": "ok"}

    def search(self, *, collections: list[str], query_text: str, top_k: int, min_score: float, file_id: str | None = None):
        return []


class _DummySlack:
    def execute_action(self, *, action: str, params: dict):
        return {"system": "slack", "action": action, "status": "success", "data": {}}


class _SleepJira:
    def execute_action(self, *, action: str, params: dict):
        time.sleep(0.35)
        return {"system": "jira", "action": action, "status": "success", "data": {"ok": True}}


class _SleepTelegram:
    def execute_action(self, *, action: str, params: dict):
        time.sleep(0.35)
        return {"system": "telegram", "action": action, "status": "success", "data": {"ok": True}}


def _deps() -> NodeDeps:
    return NodeDeps(
        llm=_DummyLLM(),
        vector_store=_DummyVector(),
        slack=_DummySlack(),
        jira=_SleepJira(),
        telegram=_SleepTelegram(),
    )


def _state(accept_parallel: bool) -> dict:
    return {
        "raw_instruction": "Do jira and telegram actions",
        "instruction": "Current User Request:\nDo jira and telegram actions",
        "accept_parallel": accept_parallel,
        "route_plan": {
            "parallel": True,
            "action_plans": [
                {
                    "system": "jira",
                    "action": "jira_search_issues",
                    "params": {"jql": "project = AIA", "maxResults": 1},
                    "risk_level": "low",
                    "depends_on": [],
                },
                {
                    "system": "telegram",
                    "action": "telegram_send_message",
                    "params": {"text": "done"},
                    "risk_level": "low",
                    "depends_on": [],
                },
            ],
        },
        "errors": [],
    }


def test_accept_parallel_true_runs_faster_than_sequential() -> None:
    deps = _deps()

    start_seq = time.perf_counter()
    seq_result = execute_actions_node(_state(False), deps)
    seq_elapsed = time.perf_counter() - start_seq
    assert len(seq_result.get("action_results", [])) == 2

    start_par = time.perf_counter()
    par_result = execute_actions_node(_state(True), deps)
    par_elapsed = time.perf_counter() - start_par
    assert len(par_result.get("action_results", [])) == 2

    # Parallel branch should be materially faster for independent actions.
    assert par_elapsed < (seq_elapsed - 0.15)
