# Technical Design Document (TDD)

## 1. Overview
AIA is a FastAPI service orchestrating:
- request enrichment + optional retrieval
- sequential action execution (Jira/Telegram; Slack fallback)
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
   - run graph (`intake -> enrichment -> rag(optional) -> answer -> route -> execute_actions -> aggregate`)
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

## 9. Known Behavioral Constraints
- Action execution is currently sequential in `execute_actions_node` (no DAG parallel execution yet)
- Upload pipeline states are updated synchronously inside request lifecycle
