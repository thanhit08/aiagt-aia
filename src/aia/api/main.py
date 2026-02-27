import csv
import hashlib
import io
import json
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency in constrained env
    def load_dotenv() -> bool:
        return False

from aia.services.factory import build_clients
from aia.workflow.graph import build_graph

load_dotenv()

app = FastAPI(title="AIA API", version="0.1.0")

llm, vector_store, slack, jira, telegram, cache_store, conversation_store, settings = build_clients()
graph = build_graph(
    llm=llm,
    vector_store=vector_store,
    slack=slack,
    jira=jira,
    telegram=telegram,
)


def _parse_upload(file: UploadFile, content: bytes) -> list[dict]:
    ct = file.content_type or ""
    text = content.decode("utf-8", errors="ignore")

    if ct == "text/csv" or file.filename.lower().endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        issues: list[dict] = []
        for idx, row in enumerate(reader, start=1):
            issues.append(
                {
                    "issue_id": str(row.get("id", idx)),
                    "title": str(row.get("title", f"Issue {idx}")).strip(),
                    "description": str(row.get("description", "")).strip() or "N/A",
                    "steps": str(row.get("steps", "N/A")).strip(),
                    "severity": str(row.get("severity", "unknown")).strip().lower(),
                }
            )
        return issues

    if ct in {"text/plain", "text/markdown"} or any(
        file.filename.lower().endswith(ext) for ext in [".txt", ".md"]
    ):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []
        return [
            {
                "issue_id": str(i + 1),
                "title": line[:120],
                "description": line,
                "steps": "N/A",
                "severity": "unknown",
            }
            for i, line in enumerate(lines)
        ]

    raise HTTPException(status_code=415, detail="Unsupported file type for this v1 API.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/conversation/{conversation_id}")
def get_conversation(conversation_id: str) -> dict:
    doc = conversation_store.get_conversation(conversation_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return doc


class IntakeJsonRequest(BaseModel):
    user_id: str = Field(min_length=1)
    instruction: str = Field(min_length=3)
    issues: list[dict] = Field(default_factory=list)
    conversation_id: str | None = None


@app.post("/qa-intake")
def qa_intake(payload: IntakeJsonRequest) -> dict:
    rate_key = f"rate:{payload.user_id}"
    current = cache_store.increment_with_ttl(rate_key, ttl_seconds=60)
    if current > settings.redis_rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    cache_key = _response_cache_key(payload.user_id, payload.instruction, payload.issues)
    cached = cache_store.get_json(cache_key)
    if cached is not None:
        return {**cached, "cached": True}

    conversation_id = payload.conversation_id or str(uuid4())
    context = conversation_store.get_context(
        conversation_id=conversation_id,
        recent_limit=settings.context_recent_messages,
    )
    merged_instruction = _merge_instruction_with_context(
        payload.instruction,
        context.get("summary", ""),
        context.get("messages", []),
    )

    request_id = str(uuid4())
    state = {
        "request_id": request_id,
        "instruction": merged_instruction,
        "parsed_issues": payload.issues,
        "user_id": payload.user_id,
    }

    conversation_store.append_message(
        conversation_id=conversation_id,
        user_id=payload.user_id,
        role="user",
        content=payload.instruction,
        tools_used=[],
        meta={"request_id": request_id},
    )

    result = graph.invoke(state)
    response = result["final_response"]
    response["conversation_id"] = conversation_id

    tools_used = [
        f"{x.get('system')}:{x.get('action')}"
        for x in response.get("action_results", [])
        if x.get("action")
    ]
    conversation_store.append_message(
        conversation_id=conversation_id,
        user_id=payload.user_id,
        role="assistant",
        content=response.get("answer", ""),
        tools_used=tools_used,
        meta={"request_id": request_id},
    )

    conversation_store.log_request_response(
        {
            "request_id": request_id,
            "conversation_id": conversation_id,
            "user_id": payload.user_id,
            "request": payload.model_dump(),
            "response": response,
        }
    )

    conversation_store.maybe_compact(
        conversation_id=conversation_id,
        max_messages=settings.context_max_messages,
        keep_recent=settings.context_recent_messages,
        summarize_fn=lambda current, old: _summarize_history(current, old),
    )

    cache_store.set_json(cache_key, response, ttl_seconds=settings.redis_response_ttl_seconds)
    return response


def _register_upload_route() -> None:
    try:
        import multipart  # noqa: F401
    except Exception:
        return

    @app.post("/qa-intake-upload")
    async def qa_intake_upload(
        file: UploadFile = File(...),
        user_id: str = Form(...),
        instruction: str = Form(...),
    ) -> dict:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        parsed_issues = _parse_upload(file, content)
        request_id = str(uuid4())
        state = {
            "request_id": request_id,
            "instruction": instruction,
            "parsed_issues": parsed_issues,
            "user_id": user_id,
        }
        result = graph.invoke(state)
        return result["final_response"]


_register_upload_route()


def _response_cache_key(user_id: str, instruction: str, issues: list[dict]) -> str:
    payload = json.dumps({"u": user_id, "i": instruction, "x": issues}, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"resp:{digest}"


def _merge_instruction_with_context(
    instruction: str, summary: str, messages: list[dict]
) -> str:
    lines = [f"Current User Request:\n{instruction}"]
    if summary:
        lines.append(f"Conversation Summary:\n{summary}")
    if messages:
        history = "\n".join(
            [f"{m.get('role', 'unknown')}: {m.get('content', '')}" for m in messages]
        )
        lines.append(f"Recent Conversation Messages:\n{history}")
    return "\n\n".join(lines)


def _summarize_history(current_summary: str, old_messages_text: str) -> str:
    sys_prompt = (
        "You summarize conversation history for memory compaction. "
        "Keep critical facts, unresolved tasks, user preferences, and tool outcomes."
    )
    user_prompt = (
        f"Existing summary:\n{current_summary}\n\n"
        f"Messages to compact:\n{old_messages_text}\n\n"
        "Return concise summary text."
    )
    text = llm.complete_text(system_prompt=sys_prompt, user_prompt=user_prompt).strip()
    return text or current_summary
