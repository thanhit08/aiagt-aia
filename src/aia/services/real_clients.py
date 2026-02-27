import json
import re
from typing import Any

import httpx

from aia.config import Settings


class OpenAILLMClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when AIA_USE_REAL_SERVICES=true")
        self._settings = settings
        self._client = httpx.Client(
            base_url=settings.openai_base_url.rstrip("/"),
            timeout=45.0,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
        )

    def complete_text(self, *, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self._settings.openai_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any] | list[Any]:
        text = self.complete_text(
            system_prompt=system_prompt + "\nReturn JSON only.",
            user_prompt=user_prompt,
        )
        return _extract_json(text)


class QdrantVectorStore:
    def __init__(self, settings: Settings) -> None:
        headers = {"Content-Type": "application/json"}
        if settings.qdrant_api_key:
            headers["api-key"] = settings.qdrant_api_key
        self._client = httpx.Client(
            base_url=settings.qdrant_url.rstrip("/"),
            timeout=20.0,
            headers=headers,
        )

    def search(
        self,
        *,
        collections: list[str],
        query_text: str,
        top_k: int,
        min_score: float,
    ) -> list[dict[str, Any]]:
        # Lightweight fallback search for local testing: scroll recent points.
        hits: list[dict[str, Any]] = []
        for collection in collections:
            payload = {"limit": top_k, "with_payload": True, "with_vector": False}
            resp = self._client.post(f"/collections/{collection}/points/scroll", json=payload)
            if resp.status_code >= 400:
                continue
            data = resp.json().get("result", {})
            for point in data.get("points", []):
                hits.append(
                    {
                        "collection": collection,
                        "score": 1.0,
                        "payload": point.get("payload", {}),
                        "id": point.get("id"),
                        "query_text": query_text,
                    }
                )
        return hits[:top_k]


class JiraApiClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.jira_base_url or not settings.jira_email or not settings.jira_api_token:
            raise ValueError("JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN are required")
        self._client = httpx.Client(
            base_url=settings.jira_base_url.rstrip("/"),
            timeout=30.0,
            auth=(settings.jira_email, settings.jira_api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )

    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "jira_search_issues":
            resp = self._client.post("/rest/api/3/search", json=params)
            return _jira_response(action, resp)
        if action == "jira_get_issue":
            issue_key = params["issue_key"]
            resp = self._client.get(f"/rest/api/3/issue/{issue_key}")
            return _jira_response(action, resp)
        if action == "jira_create_issue":
            resp = self._client.post("/rest/api/3/issue", json=params)
            data = _jira_response(action, resp)
            key = data["data"].get("key")
            if key:
                data["data"]["url"] = f"{self._client.base_url}browse/{key}"
            return data
        if action == "jira_update_issue":
            issue_key = params.pop("issue_key")
            resp = self._client.put(f"/rest/api/3/issue/{issue_key}", json=params)
            return _jira_response(action, resp)
        if action == "jira_transition_issue":
            issue_key = params.pop("issue_key")
            resp = self._client.post(f"/rest/api/3/issue/{issue_key}/transitions", json=params)
            return _jira_response(action, resp)
        if action == "jira_add_comment":
            issue_key = params.pop("issue_key")
            resp = self._client.post(f"/rest/api/3/issue/{issue_key}/comment", json=params)
            return _jira_response(action, resp)
        if action == "jira_assign_issue":
            issue_key = params.pop("issue_key")
            resp = self._client.put(f"/rest/api/3/issue/{issue_key}/assignee", json=params)
            return _jira_response(action, resp)
        if action == "jira_link_issues":
            resp = self._client.post("/rest/api/3/issueLink", json=params)
            return _jira_response(action, resp)
        if action == "jira_bulk_update":
            resp = self._client.post("/rest/api/3/issue/bulk", json=params)
            return _jira_response(action, resp)
        raise ValueError(f"Unsupported Jira action: {action}")


class SlackApiClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.slack_bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required")
        self._client = httpx.Client(
            base_url="https://slack.com/api",
            timeout=30.0,
            headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
        )

    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        mapping = {
            "slack_post_message": "chat.postMessage",
            "slack_update_message": "chat.update",
            "slack_reply_in_thread": "chat.postMessage",
            "slack_search_messages": "search.messages",
            "slack_get_channel_history": "conversations.history",
            "slack_create_channel": "conversations.create",
            "slack_archive_channel": "conversations.archive",
            "slack_invite_users": "conversations.invite",
            "slack_add_reaction": "reactions.add",
        }
        endpoint = mapping.get(action)
        if not endpoint:
            raise ValueError(f"Unsupported Slack action: {action}")

        resp = self._client.post(f"/{endpoint}", json=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok", False):
            return {"system": "slack", "action": action, "status": "failed", "error": data.get("error", "unknown")}
        return {"system": "slack", "action": action, "status": "success", "data": data}


def _jira_response(action: str, resp: httpx.Response) -> dict[str, Any]:
    if resp.status_code >= 400:
        return {
            "system": "jira",
            "action": action,
            "status": "failed",
            "error": f"http_{resp.status_code}: {resp.text[:400]}",
        }
    data = {}
    if resp.text:
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
    return {"system": "jira", "action": action, "status": "success", "data": data}


def _extract_json(text: str) -> dict[str, Any] | list[Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    first_obj = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not first_obj:
        raise ValueError("Model output is not valid JSON")
    return json.loads(first_obj.group(1))

