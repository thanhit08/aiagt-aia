# Technical Design Document (TDD)

## 1. Document Control
- System: AI Agent Toolkit (AIA)
- Owner: Engineering
- Primary Audience: Backend, AI Engineering, QA
- Status: Draft for implementation
- Last Updated: 2026-02-27

### 1.1 Update Policy
- This document defines runtime architecture, contracts, and operational controls.
- Product behavior and acceptance criteria are defined in `docs/PRD.md`.
- Diagram-only artifacts are in `docs/diagram.md`.

## 2. Architecture Summary
AIA is a query orchestration platform behind FastAPI. It supports general answers plus action execution across Jira and Slack using a connector action registry.

## 3. Technology Stack
- API: FastAPI
- Workflow: LangGraph (fallback sequential runner)
- LLM: OpenAI GPT-4o
- Vector DB: Qdrant (optional retrieval)
- Observability: LangSmith + Langfuse
- Connectors: Jira REST + Slack Web API
- Redis: response cache + rate limiting
- MongoDB: conversation/message persistence + request/response logs

### 3.1 Runtime Connector Status
- Jira connector: active.
- Telegram connector: active.
- Slack connector: intentionally disabled; Slack requests return deterministic fallback recommending Telegram.

## 4. PRD to TDD Traceability Matrix
| PRD ID | Requirement Summary | TDD Section |
| --- | --- | --- |
| FR-01 | Unified intake | 6.1 |
| FR-02 | Enrichment and intent parsing | 6.2 |
| FR-03 | Action catalog support | 6.4 |
| FR-04 | Dynamic route planning | 6.5 |
| FR-05 | Optional RAG | 6.3 |
| FR-06 | Core answer synthesis | 6.6 |
| FR-07 | Jira action execution | 6.7 |
| FR-08 | Slack action execution | 6.8 |
| FR-09 | Parallel execution | 5.2 |
| FR-10 | Safety controls | 8.3 |
| FR-11 | Observability | 6.10 |
| FR-12 | Graceful degradation | 8.2 |

## 5. Execution Model
### 5.1 Workflow Graph
`Intake -> Enrichment -> OptionalRAG -> AnswerSynthesis -> ActionPlan -> ActionExecution -> Aggregate -> Respond`

### 5.2 Concurrency Model
- Build dependency-aware action DAG from action plan.
- Execute independent actions in parallel.
- Preserve explicit sequencing for dependent actions.

## 6. Component Design
### 6.1 API Layer
- `POST /qa-intake` JSON endpoint.
- `POST /upload` multipart endpoint for asynchronous file ingestion.
- `GET /upload/{file_id}/status` for Redis-based upload state polling.
- Inputs: `instruction`, `user_id`, optional `issues`, optional file.

### 6.2 Enrichment Node
- Parse intent and output:
  - `task_type`
  - `requires_rag`
  - `output_tone`
  - `action_plans[]`
- Validate against `enriched_task` schema.

### 6.3 Optional Retrieval Node
- Trigger when query requires external knowledge/context.
- Build query spec and retrieve from Qdrant.

### 6.4 Action Registry
- Central catalog maps action ID -> executor + schema.
- Example shape:
```json
{
  "jira_search_issues": {"system": "jira", "risk": "low", "executor": "jira.search"},
  "jira_create_issue": {"system": "jira", "risk": "medium", "executor": "jira.create"},
  "slack_post_message": {"system": "slack", "risk": "low", "executor": "slack.post"},
  "slack_archive_channel": {"system": "slack", "risk": "high", "executor": "slack.archive"}
}
```

### 6.5 Route Planning Node
- Converts enriched intent into executable `action_plans`.
- Resolves defaults (assignee = current user, project from context, channel from query/profile).
- Rejects unsupported actions early with clear error.

### 6.6 Answer Synthesis Node
- Produces user-facing answer regardless of actions.
- Includes summary of planned/executed actions.

### 6.7 Jira Executor
- Supports all configured Jira actions.
- Per-action input schema validation.
- Returns structured data and links.

### 6.8 Slack Executor
- Supports all configured Slack actions.
- Per-action input schema validation.
- Returns structured data and message/channel links.

### 6.9 Aggregation Node
- Combines answer + action outcomes.
- Preserves both success and error entries.

### 6.10 Observability
- Log: intent parse, action plan, action params hash, action result status, latency.
- Trace each action step with correlation ID.

### 6.11 Redis Cache and Throttling
- Cache key: hash of `user_id + instruction + issues`.
- Cache value: final response JSON with TTL.
- Rate key: `rate:{user_id}` with 60-second window.
- If Redis unavailable, fallback to in-memory implementation.

### 6.14 File Upload State Tracking (Redis)
- File status key: `file_status:{file_id}`.
- State transitions:
  - `initiated`
  - `upload_complete`
  - `embedding`
  - `saving_to_qdrant`
  - `ready` or `failed`
- File status TTL controlled by `REDIS_FILE_STATUS_TTL_SECONDS`.

### 6.15 File-Aware RAG Retrieval
- `/qa-intake` accepts optional `file_id`.
- RAG node passes `file_id` to vector store search.
- Qdrant retrieval applies payload filter on `file_id`.

### 6.12 Conversation Store (MongoDB)
- Collections:
  - `conversations`: summary + message array + metadata
  - `request_logs`: raw request/response records with correlation IDs
- Message record fields:
  - `role` (`user` or `assistant`)
  - `content`
  - `tools_used[]`
  - `meta` (request_id, timing, optional tags)
- API supports `conversation_id`; creates one when absent.

### 6.13 Context Window Algorithm (Chosen Strategy)
- Strategy selected: `rolling summary + recent window`.
- Rules:
  - Keep last `CONTEXT_RECENT_MESSAGES` messages verbatim.
  - When total messages > `CONTEXT_MAX_MESSAGES`, summarize older block into `summary`.
  - Replace old block with summary and retained recent messages.
- Benefits:
  - bounded token usage
  - continuity of long-running conversations
  - simple deterministic storage model

## 7. Data Models
### 7.1 Enriched Task (Logical)
```json
{
  "task_type": "tool_orchestration",
  "requires_rag": false,
  "output_tone": "technical",
  "action_plans": [
    {
      "system": "jira",
      "action": "jira_search_issues",
      "params": {"jql": "project = APP AND assignee = currentUser()"},
      "risk_level": "low",
      "depends_on": []
    }
  ]
}
```

### 7.2 Final Response (Logical)
```json
{
  "request_id": "string",
  "answer": "string",
  "trace_id": "string",
  "action_results": [
    {"system": "jira", "action": "jira_search_issues", "status": "success", "data": {}},
    {"system": "slack", "action": "slack_post_message", "status": "failed", "error": "channel_not_found"}
  ],
  "errors": []
}
```

### 7.3 Conversation Document (Mongo)
```json
{
  "_id": "conversation_id",
  "user_id": "string",
  "summary": "string",
  "messages": [
    {
      "ts": "ISO-8601",
      "role": "user|assistant",
      "content": "string",
      "tools_used": ["jira:jira_search_issues", "telegram:telegram_send_message"],
      "meta": {"request_id": "string"}
    }
  ],
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601"
}
```

## 8. Reliability and Safety
### 8.1 Retry Policy
- Low-risk read/search actions: retry up to 2 times.
- Write/update actions: retry with idempotency protection.

### 8.2 Isolation Policy
- Failure in one action does not invalidate independent actions.
- Core answer is always returned if synthesis succeeds.

### 8.3 Risk Controls
- Risk levels: `low`, `medium`, `high`.
- High-risk actions (delete/archive/bulk-update) require safety policy checks.
- Optional user confirmation gate for high-risk actions.

## 9. Performance and Scaling
### 9.1 Targets
- P95 < 4s for non-file, single-action requests.
- P95 < 7s for multi-action requests.

### 9.2 Scaling
- Stateless API workers.
- Shared Qdrant and connector pools.
- Per-user and per-system rate limiting.

## 10. Security
- Per-system OAuth/token scope validation.
- Action-level authorization checks.
- Sensitive data redaction in logs.
- Audit records for all external actions.

## 11. Testing Strategy
- Unit: intent parsing, action schema validation, risk policy checks.
- Integration: Jira/Slack read and write action suites.
- E2E: multi-action queries with mixed success/failure.
- Regression: action catalog compatibility tests.

## 12. v1 Implementation Assets
- Schemas and prompt templates in `specs/v1/`.
- Existing code should migrate from boolean route flags to `action_plans[]` execution model.
