from aia.workflow.nodes import NodeDeps, execute_actions_node


class _DummyLLM:
    def complete_json(self, *, system_prompt: str, user_prompt: str):
        return {"chat_id": "-999", "text": "hello"}

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        return "ok"


class _DummyVector:
    def upsert_chunks(self, *, file_id: str, chunks: list[str]):
        return {"status": "ok"}

    def search(self, *, collections: list[str], query_text: str, top_k: int, min_score: float, file_id: str | None = None):
        return []


class _DummyNoop:
    def execute_action(self, *, action: str, params: dict):
        return {"system": "jira", "action": action, "status": "success", "data": {}}


class _DummyTelegram:
    def __init__(self) -> None:
        self.last_params = {}

    def execute_action(self, *, action: str, params: dict):
        self.last_params = dict(params)
        return {"system": "telegram", "action": action, "status": "success", "data": {"sent": True}}


def _deps(telegram_client: _DummyTelegram) -> NodeDeps:
    return NodeDeps(
        llm=_DummyLLM(),
        vector_store=_DummyVector(),
        slack=_DummyNoop(),
        jira=_DummyNoop(),
        telegram=telegram_client,
    )


def test_telegram_chat_id_from_model_is_ignored_by_default() -> None:
    telegram = _DummyTelegram()
    state = {
        "raw_instruction": "send to telegram",
        "instruction": "Current User Request:\nsend to telegram",
        "route_plan": {
            "parallel": True,
            "action_plans": [
                {
                    "system": "telegram",
                    "action": "telegram_send_message",
                    "params": {"chat_id": "-123", "text": "x"},
                    "risk_level": "low",
                    "depends_on": [],
                }
            ],
        },
        "errors": [],
    }
    execute_actions_node(state, _deps(telegram))
    assert "chat_id" not in telegram.last_params


def test_telegram_chat_id_from_request_is_used() -> None:
    telegram = _DummyTelegram()
    state = {
        "raw_instruction": "send to telegram",
        "instruction": "Current User Request:\nsend to telegram",
        "telegram_chat_id": "-10012345",
        "route_plan": {
            "parallel": True,
            "action_plans": [
                {
                    "system": "telegram",
                    "action": "telegram_send_message",
                    "params": {"text": "x"},
                    "risk_level": "low",
                    "depends_on": [],
                }
            ],
        },
        "errors": [],
    }
    execute_actions_node(state, _deps(telegram))
    assert telegram.last_params.get("chat_id") == "-10012345"
