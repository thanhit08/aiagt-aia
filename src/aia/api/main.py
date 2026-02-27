import csv
import io
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

llm, vector_store, slack, jira = build_clients()
graph = build_graph(
    llm=llm,
    vector_store=vector_store,
    slack=slack,
    jira=jira,
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


class IntakeJsonRequest(BaseModel):
    user_id: str = Field(min_length=1)
    instruction: str = Field(min_length=3)
    issues: list[dict] = Field(default_factory=list)


@app.post("/qa-intake")
def qa_intake(payload: IntakeJsonRequest) -> dict:
    request_id = str(uuid4())
    state = {
        "request_id": request_id,
        "instruction": payload.instruction,
        "parsed_issues": payload.issues,
        "user_id": payload.user_id,
    }
    result = graph.invoke(state)
    return result["final_response"]


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
