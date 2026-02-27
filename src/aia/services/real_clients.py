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
        self._upload_collection = settings.qdrant_upload_collection
        self._ensure_collection(self._upload_collection)

    def upsert_chunks(self, *, file_id: str, chunks: list[str]) -> dict[str, Any]:
        points = []
        for idx, chunk in enumerate(chunks):
            # Deterministic lightweight vector for local testability without embedding dependency.
            val = float((abs(hash(chunk)) % 1000) / 1000.0)
            points.append(
                {
                    "id": abs(hash(f"{file_id}:{idx}")) % (10**12),
                    "vector": [val],
                    "payload": {
                        "file_id": file_id,
                        "chunk_index": idx,
                        "text": chunk,
                    },
                }
            )
        payload = {"points": points}
        resp = self._client.put(f"/collections/{self._upload_collection}/points", json=payload)
        resp.raise_for_status()
        return {"status": "ok", "stored_chunks": len(chunks), "file_id": file_id}

    def search(
        self,
        *,
        collections: list[str],
        query_text: str,
        top_k: int,
        min_score: float,
        file_id: str | None = None,
    ) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for collection in collections:
            filter_payload: dict[str, Any] | None = None
            if file_id:
                filter_payload = {
                    "must": [{"key": "file_id", "match": {"value": file_id}}],
                }
            payload = {
                "limit": top_k,
                "with_payload": True,
                "with_vector": False,
            }
            if filter_payload:
                payload["filter"] = filter_payload
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

    def _ensure_collection(self, name: str) -> None:
        resp = self._client.get(f"/collections/{name}")
        if resp.status_code == 200:
            return
        payload = {"vectors": {"size": 1, "distance": "Cosine"}}
        create = self._client.put(f"/collections/{name}", json=payload)
        create.raise_for_status()


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
            # Jira Cloud deprecated /search for some tenants; prefer /search/jql and fallback.
            primary = self._client.post("/rest/api/3/search/jql", json=params)
            if primary.status_code in {404, 405, 410}:
                fallback = self._client.post("/rest/api/3/search", json=params)
                return _jira_response(action, fallback)
            return _jira_response(action, primary)
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


class TelegramApiClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        self._default_chat_id = settings.telegram_default_chat_id
        self._client = httpx.Client(
            base_url=f"https://api.telegram.org/bot{settings.telegram_bot_token}",
            timeout=30.0,
            headers={"Content-Type": "application/json"},
        )

    def execute_action(self, *, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "telegram_send_message":
            payload = dict(params)
            if "chat_id" not in payload and self._default_chat_id:
                payload["chat_id"] = self._default_chat_id
            if "chat_id" not in payload:
                return {
                    "system": "telegram",
                    "action": action,
                    "status": "failed",
                    "error": "chat_id is required (or set TELEGRAM_DEFAULT_CHAT_ID)",
                }
            resp = self._client.post("/sendMessage", json=payload)
            if resp.status_code >= 400:
                return _telegram_error(action, resp)
            data = _safe_json(resp)
            if not data.get("ok", False):
                return {
                    "system": "telegram",
                    "action": action,
                    "status": "failed",
                    "error": str(data.get("description", "unknown")),
                }
            return {"system": "telegram", "action": action, "status": "success", "data": data.get("result", {})}

        if action == "telegram_get_updates":
            resp = self._client.post("/getUpdates", json=params or {})
            if resp.status_code >= 400:
                return _telegram_error(action, resp)
            data = _safe_json(resp)
            if not data.get("ok", False):
                return {
                    "system": "telegram",
                    "action": action,
                    "status": "failed",
                    "error": str(data.get("description", "unknown")),
                }
            return {"system": "telegram", "action": action, "status": "success", "data": data.get("result", [])}

        raise ValueError(f"Unsupported Telegram action: {action}")


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


def _safe_json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data
        return {"raw": data}
    except Exception:
        return {"raw": resp.text}


def _telegram_error(action: str, resp: httpx.Response) -> dict[str, Any]:
    data = _safe_json(resp)
    desc = data.get("description")
    if not isinstance(desc, str) or not desc.strip():
        desc = resp.text[:400] or f"http_{resp.status_code}"
    hint = ""
    lower = desc.lower()
    if "chat not found" in lower:
        hint = " Verify TELEGRAM_DEFAULT_CHAT_ID and send a message to the bot first."
    elif "bot was blocked" in lower:
        hint = " Unblock the bot from Telegram and retry."
    elif "user is deactivated" in lower:
        hint = " The destination account is deactivated."
    return {
        "system": "telegram",
        "action": action,
        "status": "failed",
        "error": f"http_{resp.status_code}: {desc}{hint}",
    }


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
