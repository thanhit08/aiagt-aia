# Technical Design Document (TDD)

## 1. Overview
AIA is a FastAPI service orchestrating:
- request enrichment + optional retrieval
- dependency-aware action execution (sequential or parallel based on config + dependencies)
- Redis cache/rate-limit/file-status tracking
- MongoDB conversation + request log persistence

## 2. Runtime Architecture (Implemented)
1. `POST /upload`:
   - derive `file_id` from filename hash
   - write upload metadata + state transitions in Redis
   - parse file into chunks and upsert into Qdrant with payload `file_id`
2. `POST /qa-intake`:
   - rate limit per user via Redis
   - response cache lookup via Redis
   - load conversation summary + recent messages from Mongo
   - merge context into instruction
   - run graph (`intake -> rag_check -> rag_query_enrichment(optional) -> rag(optional) -> route -> execute_actions -> aggregate`)
   - persist user+assistant messages and request/response log to Mongo
   - compact history using rolling summary when threshold exceeded
3. `GET /conversation/{conversation_id}`:
   - return persisted conversation document
4. `GET /upload/{file_id}` and `GET /upload/{file_id}/status`:
   - return metadata/status from Redis

## 3. Technology Stack
- FastAPI
- LangGraph (with fallback runner)
- OpenAI Chat Completions API
- Qdrant
- Redis
- MongoDB
- Jira REST API
- Telegram Bot API

## 4. Connector Status
- Jira: active
- Telegram: active
- Slack: disabled for execution, returns fallback error suggesting Telegram

## 5. Data Models (Implemented)
### 5.1 Conversation document
```json
{
  "_id": "conversation_id",
  "user_id": "string",
  "summary": "string",
  "messages": [
    {
      "ts": "ISO",
      "role": "user|assistant",
      "content": "string",
      "tools_used": ["jira:jira_search_issues"],
      "meta": {"request_id": "string"}
    }
  ],
  "created_at": "ISO",
  "updated_at": "ISO"
}
```

### 5.2 Upload Redis keys
- Metadata: `file_meta:{file_id}`
- Status: `file_status:{file_id}`
- Stages: `initiated -> upload_complete -> embedding -> saving_to_qdrant -> ready|failed`

## 6. Context Window Algorithm (Chosen)
Single strategy: **rolling summary + recent window**
- Keep `CONTEXT_RECENT_MESSAGES` raw messages
- If message count exceeds `CONTEXT_MAX_MESSAGES`:
  - summarize older block with LLM
  - store summary
  - retain only recent messages

## 7. RAG File Filter
- `/qa-intake` accepts `file_id`
- Node passes `file_id` to vector store search
- Qdrant query uses payload filter on `file_id`

## 8. Reliability Notes
- Redis unavailable: in-memory cache fallback
- Mongo unavailable: in-memory conversation fallback
- Slack action requested: deterministic failed action result with Telegram suggestion

## 9. Action Execution Algorithm (Implemented)
### 9.1 Mode selection
- `ACCEPT_PARALLEL=false` (default): sequential execution.
- `ACCEPT_PARALLEL=true`: parallel execution for dependency-independent actions.
- Request can override via `/qa-intake` payload field `accept_parallel`.

### 9.2 Dependency rules
- `depends_on` is authoritative.
- An action runs only when all dependencies succeeded.
- If a dependency failed/skipped, dependent action is marked `skipped`.
- Action results are returned in original route plan order for deterministic UI/testing.

### 9.3 Automatic grouping strategy (route/runtime)
- Build dependency layers from action plan graph:
  - layer N contains actions whose dependencies are all in layers `< N`
- Execution semantics:
  - run all actions in the same layer in parallel (when parallel mode enabled)
  - run layers sequentially (layer 0 -> layer 1 -> layer 2 ...)
- This yields automatic split between:
  - **parallel group**: independent actions in same layer
  - **sequential group**: dependency chain across layers
- If planner over-specifies dependencies, they are honored (safety first).
- If unresolved/cyclic dependency remains, affected actions are marked `skipped`.

### 9.4 Parallel vs sequential patterns
- Parallel-eligible (independent actions):
  - `jira_create_issue` + `telegram_send_message` with no cross-dependency
  - `jira_search_issues` + `telegram_send_message` with no cross-dependency
- Must stay sequential (data dependency):
  - `jira_search_issues -> telegram_send_message` when Telegram content depends on Jira search output
  - `jira_create_issue -> jira_assign_issue` (needs created `issue_key`)
  - any chain declared via `depends_on`

### 9.5 Practical examples
- Example A (parallel):
  - User asks: "Create Jira ticket and notify Telegram"
  - Plan: two actions, both `depends_on=[]` -> run concurrently.
- Example B (sequential):
  - User asks: "Search Jira issues assigned to me, then send summary to Telegram"
  - Plan: `telegram_send_message.depends_on=['jira_search_issues']` -> run in order.

## 10. Known Behavioral Constraints
- Upload pipeline states are updated synchronously inside request lifecycle
