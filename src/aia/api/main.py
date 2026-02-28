import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency in constrained env
    def load_dotenv() -> bool:
        return False

from aia.services.factory import build_clients
from aia.workflow.nodes import (
    NodeDeps,
    aggregate_node,
    answer_node,
    enrichment_node,
    execute_actions_node,
    intake_node,
    rag_context_node,
    route_node,
)
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
node_deps = NodeDeps(llm=llm, vector_store=vector_store, slack=slack, jira=jira, telegram=telegram)


def _parse_upload(file: UploadFile, content: bytes) -> list[str]:
    ct = file.content_type or ""
    text = content.decode("utf-8", errors="ignore")

    if ct in {"text/plain", "text/markdown", "text/csv"} or any(
        file.filename.lower().endswith(ext) for ext in [".txt", ".md", ".csv"]
    ):
        return [line.strip() for line in text.splitlines() if line.strip()]

    raise HTTPException(status_code=415, detail="Unsupported file type for upload.")


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
    request_id: str | None = None
    conversation_id: str | None = None
    file_id: str | None = None


@app.post("/qa-intake")
def qa_intake(payload: IntakeJsonRequest) -> dict:
    request_id = payload.request_id or str(uuid4())
    rate_key = f"rate:{payload.user_id}"
    current = cache_store.increment_with_ttl(rate_key, ttl_seconds=60)
    if current > settings.redis_rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")

    cache_key = _response_cache_key(payload.user_id, payload.instruction, payload.file_id)
    cached = cache_store.get_json(cache_key)
    if cached is not None:
        existing = cache_store.get_json(_request_status_key(request_id)) or {}
        _set_request_status(
            request_id=request_id,
            state="completed",
            current_node="done",
            step_index=len(_workflow_steps()),
            total_steps=len(_workflow_steps()),
            user_id=payload.user_id,
            step_details=existing.get("step_details"),
        )
        return {**cached, "request_id": request_id, "cached": True}

    conversation_id = payload.conversation_id or str(uuid4())
    _set_request_status(
        request_id=request_id,
        state="running",
        current_node="intake",
        step_index=0,
        total_steps=len(_workflow_steps()),
        user_id=payload.user_id,
    )
    context = conversation_store.get_context(
        conversation_id=conversation_id,
        recent_limit=settings.context_recent_messages,
    )
    merged_instruction = _merge_instruction_with_context(
        payload.instruction,
        context.get("summary", ""),
        context.get("messages", []),
    )

    state = {
        "request_id": request_id,
        "instruction": merged_instruction,
        "user_id": payload.user_id,
        "file_id": payload.file_id,
    }

    conversation_store.append_message(
        conversation_id=conversation_id,
        user_id=payload.user_id,
        role="user",
        content=payload.instruction,
        tools_used=[],
        meta={"request_id": request_id},
    )

    result = _invoke_graph_with_status(state, request_id=request_id, user_id=payload.user_id)
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
    existing = cache_store.get_json(_request_status_key(request_id)) or {}
    _set_request_status(
        request_id=request_id,
        state="completed",
        current_node="done",
        step_index=len(_workflow_steps()),
        total_steps=len(_workflow_steps()),
        user_id=payload.user_id,
        step_details=existing.get("step_details"),
    )
    return response


@app.get("/qa-intake/{request_id}/status")
def qa_intake_status(request_id: str) -> dict:
    status = cache_store.get_json(_request_status_key(request_id))
    if not status:
        raise HTTPException(status_code=404, detail="Request status not found.")
    return status


def _register_upload_route() -> None:
    try:
        import multipart  # noqa: F401
    except Exception:
        return

    @app.post("/upload")
    async def upload_file(
        file: UploadFile = File(...),
        user_id: str = Form(...),
    ) -> dict:
        file_id = _file_id_from_filename(file.filename)
        status_key = _file_status_key(file_id)
        meta_key = _file_meta_key(file_id)
        cache_store.set_json(
            meta_key,
            {
                "file_id": file_id,
                "filename": file.filename,
                "user_id": user_id,
                "content_type": file.content_type or "application/octet-stream",
                "status_key": status_key,
            },
            ttl_seconds=settings.redis_file_status_ttl_seconds,
        )
        cache_store.set_json(
            status_key,
            {
                "file_id": file_id,
                "filename": file.filename,
                "state": "initiated",
                "progress": 0,
                "user_id": user_id,
            },
            ttl_seconds=settings.redis_file_status_ttl_seconds,
        )

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        chunks = _parse_upload(file, content)
        cache_store.set_json(
            status_key,
            {
                "file_id": file_id,
                "filename": file.filename,
                "state": "upload_complete",
                "progress": 20,
                "user_id": user_id,
                "chunks": len(chunks),
            },
            ttl_seconds=settings.redis_file_status_ttl_seconds,
        )
        cache_store.set_json(
            status_key,
            {
                "file_id": file_id,
                "filename": file.filename,
                "state": "embedding",
                "progress": 60,
                "user_id": user_id,
                "chunks": len(chunks),
            },
            ttl_seconds=settings.redis_file_status_ttl_seconds,
        )

        cache_store.set_json(
            status_key,
            {
                "file_id": file_id,
                "filename": file.filename,
                "state": "saving_to_qdrant",
                "progress": 85,
                "user_id": user_id,
                "chunks": len(chunks),
            },
            ttl_seconds=settings.redis_file_status_ttl_seconds,
        )
        try:
            upsert_result = vector_store.upsert_chunks(file_id=file_id, chunks=chunks)
        except Exception as exc:
            cache_store.set_json(
                status_key,
                {
                    "file_id": file_id,
                    "filename": file.filename,
                    "state": "failed",
                    "progress": 100,
                    "user_id": user_id,
                    "error": str(exc),
                },
                ttl_seconds=settings.redis_file_status_ttl_seconds,
            )
            raise HTTPException(status_code=500, detail=f"Failed to store file in vector db: {exc}")

        cache_store.set_json(
            status_key,
            {
                "file_id": file_id,
                "filename": file.filename,
                "state": "ready",
                "progress": 100,
                "user_id": user_id,
                "chunks": len(chunks),
                "vector_store": upsert_result,
            },
            ttl_seconds=settings.redis_file_status_ttl_seconds,
        )

        return {"file_id": file_id, "status": "ready", "chunks": len(chunks)}

    @app.get("/upload/{file_id}")
    def upload_meta(file_id: str) -> dict:
        meta = cache_store.get_json(_file_meta_key(file_id))
        if not meta:
            raise HTTPException(status_code=404, detail="File metadata not found.")
        return meta

    @app.get("/upload/{file_id}/status")
    def upload_status(file_id: str) -> dict:
        status = cache_store.get_json(_file_status_key(file_id))
        if not status:
            raise HTTPException(status_code=404, detail="File status not found.")
        return status


_register_upload_route()


def _response_cache_key(user_id: str, instruction: str, file_id: str | None) -> str:
    payload = json.dumps(
        {"u": user_id, "i": instruction, "f": file_id or ""},
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"resp:{digest}"


def _request_status_key(request_id: str) -> str:
    return f"request_status:{request_id}"


def _workflow_steps() -> list[str]:
    return ["intake", "enrichment", "rag", "answer", "route", "execute_actions", "aggregate", "done"]


def _set_request_status(
    *,
    request_id: str,
    state: str,
    current_node: str,
    step_index: int,
    total_steps: int,
    user_id: str,
    error: str | None = None,
    step_details: list[dict] | None = None,
) -> None:
    payload = {
        "request_id": request_id,
        "state": state,
        "current_node": current_node,
        "step_index": step_index,
        "total_steps": total_steps,
        "steps": _workflow_steps(),
        "user_id": user_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if error:
        payload["error"] = error
    if step_details is not None:
        payload["step_details"] = step_details
    cache_store.set_json(
        _request_status_key(request_id),
        payload,
        ttl_seconds=settings.redis_response_ttl_seconds,
    )


def _invoke_graph_with_status(state: dict, *, request_id: str, user_id: str) -> dict:
    steps = _workflow_steps()
    current: dict = dict(state)
    step_details: list[dict] = []
    pipeline = [
        ("intake", lambda s: intake_node(s)),
        ("enrichment", lambda s: enrichment_node(s, node_deps)),
        ("rag", lambda s: rag_context_node(s, node_deps)),
        ("answer", lambda s: answer_node(s, node_deps)),
        ("route", lambda s: route_node(s, node_deps)),
        ("execute_actions", lambda s: execute_actions_node(s, node_deps)),
        ("aggregate", lambda s: aggregate_node(s)),
    ]
    try:
        for idx, (node_name, fn) in enumerate(pipeline, start=1):
            step_input = _step_snapshot(current)
            detail = {
                "node": node_name,
                "state": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "input": step_input,
            }
            step_details.append(detail)
            _set_request_status(
                request_id=request_id,
                state="running",
                current_node=node_name,
                step_index=idx,
                total_steps=len(steps),
                user_id=user_id,
                step_details=step_details,
            )
            update = fn(current)
            if isinstance(update, dict):
                current.update(update)
            detail["state"] = "completed"
            detail["finished_at"] = datetime.now(timezone.utc).isoformat()
            detail["output"] = _step_snapshot(update if isinstance(update, dict) else {"value": str(update)})
            _set_request_status(
                request_id=request_id,
                state="running",
                current_node=node_name,
                step_index=idx,
                total_steps=len(steps),
                user_id=user_id,
                step_details=step_details,
            )
        return current
    except Exception as exc:
        if step_details:
            step_details[-1]["state"] = "failed"
            step_details[-1]["finished_at"] = datetime.now(timezone.utc).isoformat()
            step_details[-1]["error"] = str(exc)
        _set_request_status(
            request_id=request_id,
            state="failed",
            current_node=node_name if "node_name" in locals() else "failed",
            step_index=idx if "idx" in locals() else 0,
            total_steps=len(steps),
            user_id=user_id,
            error=str(exc),
            step_details=step_details if step_details else None,
        )
        raise


def _step_snapshot(data: dict) -> dict:
    allow_keys = {
        "request_id",
        "instruction",
        "enriched_task",
        "rag_context",
        "answer",
        "route_plan",
        "action_results",
        "errors",
        "final_response",
        "trace_id",
        "file_id",
    }
    out: dict = {}
    for key in allow_keys:
        if key in data:
            out[key] = _truncate_json_value(data[key])
    return out


def _truncate_json_value(value, *, max_text: int = 400, max_items: int = 10):
    if isinstance(value, str):
        if len(value) <= max_text:
            return value
        return value[:max_text] + "...(truncated)"
    if isinstance(value, list):
        return [_truncate_json_value(v, max_text=max_text, max_items=max_items) for v in value[:max_items]]
    if isinstance(value, dict):
        out: dict = {}
        items = list(value.items())[:max_items]
        for k, v in items:
            out[str(k)] = _truncate_json_value(v, max_text=max_text, max_items=max_items)
        return out
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _file_id_from_filename(filename: str) -> str:
    normalized = (filename or "").strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:24]


def _file_status_key(file_id: str) -> str:
    return f"file_status:{file_id}"


def _file_meta_key(file_id: str) -> str:
    return f"file_meta:{file_id}"


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
