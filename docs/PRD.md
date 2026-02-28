# Product Requirements Document (PRD)

## 1. Document Control
- Product: AI Agent Toolkit (AIA)
- Owner: Product Manager
- Status: Draft for implementation
- Last Updated: 2026-02-28

## 2. Product Summary
AIA is a query orchestration API with:
- Conversation memory (MongoDB)
- Cache/rate-limit/status tracking (Redis)
- File upload pipeline (`/upload`) separate from messaging (`/qa-intake`)
- Optional file-scoped retrieval via Qdrant `file_id` filter
- Tool actions for Jira and Telegram

## 3. Current Integration Status
- Jira: supported
- Telegram: supported (recommended messaging output)
- Slack: currently not supported for execution; requests return deterministic fallback guidance to Telegram

## 4. Goals
- Support multi-turn conversational requests.
- Persist conversation/messages/tool-usage history.
- Keep context bounded via rolling summary + recent window.
- Separate file ingestion from chat flow.
- Provide observable file processing status.
- Support configurable sequential vs parallel tool execution.

## 5. Scope
### 5.1 In Scope
- `POST /upload`: file ingestion and vectorization trigger.
- `GET /upload/{file_id}/status`: upload progress from Redis.
- `GET /upload/{file_id}`: upload metadata from Redis.
- `POST /qa-intake`: conversation + optional `file_id` request flow.
- `GET /conversation/{conversation_id}`: inspect stored conversation.
- Redis response caching + rate limiting.
- MongoDB request/response + conversation persistence.
- Qdrant retrieval filtered by `file_id` when provided.
- Configurable action execution mode (sequential/parallel).

### 5.2 Out of Scope
- Slack live execution.
- Asynchronous background worker queue (current upload pipeline is synchronous status progression).

## 6. Functional Requirements
- FR-01 User can upload files independently from chat requests.
- FR-02 System generates deterministic `file_id` from filename hash.
- FR-03 System stores upload status lifecycle in Redis.
- FR-04 User can query upload status by `file_id`.
- FR-05 User can send conversation request with optional `file_id`.
- FR-06 RAG retrieval filters by `file_id` when present.
- FR-07 System persists conversation turns with `tools_used`.
- FR-08 System persists request/response audit logs.
- FR-09 System compacts long history using rolling summary + recent window.
- FR-10 Slack requests return fallback recommendation to Telegram.
- FR-11 System supports configurable action execution mode:
  - sequential when parallel mode is disabled
  - parallel for dependency-independent actions when enabled
- FR-12 User can override action execution mode per request via `accept_parallel`.
- FR-13 System enforces dependency ordering (`depends_on`) even when parallel mode is enabled.
- FR-14 System automatically groups actions at route/runtime into:
  - parallel groups (independent actions in same dependency layer)
  - sequential groups (actions with data/order dependencies)
- FR-15 System should not require manual dependency authoring for common patterns; policy layer infers safe grouping from action intent and preserves explicit dependencies.

## 7. Data Contracts (Implemented)
### 7.1 `/upload` response
```json
{
  "file_id": "string",
  "status": "ready",
  "chunks": 3
}
```

### 7.2 `/upload/{file_id}/status` response
```json
{
  "file_id": "string",
  "state": "ready",
  "progress": 100
}
```

### 7.3 `/qa-intake` response
```json
{
  "request_id": "string",
  "answer": "string",
  "trace_id": "string",
  "action_results": [],
  "errors": [],
  "conversation_id": "string"
}
```

## 8. Acceptance Criteria
- AC-01 Upload and chat are operationally independent.
- AC-02 Upload status endpoint reflects processing stages.
- AC-03 Chat with `file_id` uses file-scoped retrieval.
- AC-04 Conversation endpoint returns message history and tools used.
- AC-05 Long history is compacted without losing continuity.
- AC-06 Slack requests return explicit not-supported response with Telegram guidance.
- AC-07 With parallel mode enabled, independent Jira + Telegram actions can execute concurrently.
- AC-08 With dependency chains, actions execute sequentially according to `depends_on`.
- AC-09 Action result order remains deterministic and follows route plan order.
- AC-10 For mixed plans, system executes by dependency layers automatically (parallel within layer, sequential across layers).
