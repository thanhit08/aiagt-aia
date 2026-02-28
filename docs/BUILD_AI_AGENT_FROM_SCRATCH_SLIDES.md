# Build an AI Agent From Scratch in Python
## Beginner Tutorial + Real-World Bug Fix Journey

**Project:** AIA (Actionable Intelligence Agent)  
**Stack:** FastAPI, LangGraph-style workflow, Qdrant, Redis, MongoDB, Jira/Telegram, Streamlit (UI)

---

## 1. Why Build This?
- Users ask in natural language.
- Agent decides what to do.
- Agent can retrieve file context (RAG).
- Agent can execute real actions (Jira, Telegram).

**Goal:** move from "chatbot" to "workflow automation agent".

---

## 2. What This System Does
- Accept user requests via API.
- Optional file upload for retrieval (RAG).
- Plan actions (route plan).
- Execute tools.
- Aggregate final response.
- Store conversation history and status.

---

## 3. High-Level Architecture
- **API layer:** FastAPI (`/qa-intake`, `/upload`, status endpoints)
- **Workflow layer:** nodes + orchestration
- **Memory/State:** Redis + MongoDB
- **Knowledge retrieval:** Qdrant
- **Tool adapters:** Jira, Telegram
- **UI:** Streamlit (for testing/visual workflow)

---

## 4. Current Workflow (Implemented)
1. Intake
2. RAG Check (based on `file_id`)
3. RAG Query Enrichment (query optimization only)
4. RAG Retrieval + context compile
5. Route (build action plans)
6. Execute actions
7. Aggregate

---

## 5. Why This Workflow Matters
- Separates retrieval from action planning.
- Keeps action planning grounded in RAG result.
- Makes debugging easier (node-by-node status).
- Avoids mixing unrelated concerns in one LLM call.

---

## 6. Data & Integrations
- **Qdrant:** file chunks with `file_id` filter.
- **Redis:**
  - request status progress
  - upload progress states
  - rate limit + short-term cache
- **MongoDB:**
  - conversations
  - user/assistant messages
  - tools used per message

---

## 7. Streamlit Role (UI only)
- Upload file and get `file_id`
- Submit user request
- Poll status endpoint
- Render workflow steps and details

**Note:** Streamlit is a test UI; business logic stays in API/workflow backend.

---

## 8. Critical Bug #1 - Enrichment Validation 500
**Symptom:** `/qa-intake` returned 500 from Pydantic validation.  
**Root cause:** LLM output didn’t match strict schema (wrong enum values, missing required fields, wrong types).  
**Fix:** normalization layer before validation + safe fallback object.

---

## 9. Critical Bug #2 - Unsupported Actions
**Symptom:** actions like `telegram_send_to_telegram` failed.  
**Root cause:** planner emitted non-canonical action names.  
**Fix:** strict action catalog + aliases + runtime normalization.

---

## 10. Critical Bug #3 - Wrong Route Plan (Unwanted Jira Search)
**Symptom:** `jira_search_issues` was added even when user asked file->Telegram + create Jira tickets.  
**Root cause:** intent parser too narrow (missed phrase variants like “create Jira tickets”).  
**Fix:** stronger intent rules + explicit policy: search Jira only when asked.

---

## 11. Critical Bug #4 - Telegram `chat not found`
**Symptom:** Telegram sending failed after workflow refactor.  
**Root cause:** model/planner-generated `chat_id` overrode trusted defaults.  
**Fix:** protect routing params; only allow `chat_id` from trusted API input or env default.

---

## 12. Critical Bug #5 - Jira Search Endpoint Incompatibility
**Symptom:** tenant-specific failures (`/search` vs `/search/jql`).  
**Root cause:** Jira Cloud API differences across tenants.  
**Fix:** compatible fallback sequence (POST/GET on both endpoints).

---

## 13. Critical Bug #6 - Jira Scope Migration (Project -> Space)
**Symptom:** issue creation failed after Jira taxonomy change.  
**Root cause:** payload/config assumed `project` only.  
**Fix:**
- `JIRA_SCOPE_MODE=auto|space|project`
- prefer space keys, fallback to project keys
- create-issue retry with toggled payload field (`space` <-> `project`)

---

## 14. Critical Bug #7 - Stale Failed Responses
**Symptom:** after a fix, user still got old failure response.  
**Root cause:** failed responses were cached by Redis key.  
**Fix:** cache only successful responses.

---

## 15. Critical Bug #8 - Workflow UI Appeared Stuck
**Symptom:** status stayed at intake then jumped to done.  
**Root cause:** event-stream granularity mismatch.  
**Fix:** deterministic step-by-step status updates from backend node execution.

---

## 16. Engineering Practices We Applied
- Normalize model output before schema validation.
- Keep strict fixed action catalog.
- Separate concerns per node.
- Add regression tests for every production bug.
- Log each error with: symptom -> root cause -> fix -> prevention.

---

## 17. Minimal Local Run (Concept)
1. Start infra (Redis, MongoDB, Qdrant, API).
2. Upload file via `/upload`.
3. Call `/qa-intake` with `file_id`.
4. Poll `/qa-intake/{request_id}/status`.
5. Verify tool results (Telegram/Jira).

---

## 18. Beginner Takeaways
- Start with a simple, observable workflow.
- Treat LLM output as untrusted input.
- Retrieval and action planning should be separate steps.
- Real integrations fail in many ways; build fallback logic.
- Good docs + tests are part of “agent reliability.”

---

## 19. Next Steps (V2 Ideas)
- Add approval gates for medium/high-risk actions.
- Add per-tenant capability flags for Jira/Telegram variants.
- Add richer observability dashboards.
- Add load tests for concurrent requests.

---

## 20. Deep Dive - Concurrency/Parallelism
- Add `ACCEPT_PARALLEL` (env) and `accept_parallel` (request override).
- Use dependency-aware execution:
  - automatically group actions by dependency layers
  - run parallel inside each layer
  - run sequential across layers
- Keep deterministic output ordering by route plan index.

**Parallel example:** `jira_create_issue` + `telegram_send_message` (no data dependency)  
**Sequential example:** `jira_search_issues -> telegram_send_message` (summary depends on search)

---

## 21. Deep Dive - Why This Improves Performance
- Lower end-to-end latency for multi-tool requests.
- Better user experience in UI (visible concurrent progress).
- No loss of safety because dependency chains are still enforced.
- Easy comparison in Streamlit with runtime timers.

---

## 22. Deep Dive - Automatic Switch Strategy
1. Route produces `action_plans` with `depends_on`.
2. Executor builds dependency layers from the plan.
3. If parallel mode is enabled:
   - execute each layer in parallel
   - move to next layer only after completion
4. If parallel mode is disabled:
   - execute in sequential order (compatibility mode)
5. Always return results in original route order.

---

## 23. Final Message
A production-ready AI agent is not just prompts.  
It is **workflow design + validation + fallback + testing + operations discipline**.
