# Technical Design Document (TDD)

## 1. Document Control
- System: Accuracy Intelligence Agent (AIA)
- Owner: Engineering
- Primary Audience: Backend, AI Engineering, QA
- Status: Draft for implementation
- Last Updated: 2026-02-27

### 1.1 Update Policy
- This document is the source of truth for architecture, execution behavior, data models, and operational constraints.
- Product scope and acceptance criteria are owned by `docs/PRD.md`.
- Diagram-only artifacts are maintained in `docs/diagram.md`.

## 2. Architecture Summary
AIA is a LangGraph-driven workflow behind a FastAPI endpoint. It performs request enrichment, RAG grounding, issue classification, confidence filtering, then parallel Slack/Jira execution with observability.

## 3. Technology Stack
- API: FastAPI
- Workflow Engine: LangGraph
- LLM: OpenAI GPT-4o
- Embeddings: text-embedding-3-small
- Vector Database: Qdrant
- Observability: LangSmith
- Analytics: Langfuse
- Concurrency: asyncio + graph branch parallelism

## 4. PRD to TDD Traceability Matrix
| PRD ID | Requirement Summary | TDD Section |
| --- | --- | --- |
| FR-01 | File intake endpoint and formats | 6.1, 8.1 |
| FR-02 | Request enrichment contract | 6.2 |
| FR-03 | Accuracy definition retrieval via RAG | 6.3 |
| FR-04 | Issue classification schema | 6.4, 7.2 |
| FR-05 | Confidence-based filter | 6.5 |
| FR-06 | Specialized orchestration prompts | 6.6 |
| FR-07 | Slack summary and URL | 6.7 |
| FR-08 | Jira create/skip duplicate behavior | 6.8 |
| FR-09 | Parallel Slack and Jira execution | 5.2, 6.9 |
| FR-10 | Trace and metrics emission | 6.10 |
| NFR-01 | P95 latency target | 9.1 |
| NFR-02 | Scalability model | 9.2 |
| NFR-03 | Reliability and isolation | 8.2 |
| NFR-04 | Security controls | 10 |

## 5. Execution Model
### 5.1 Workflow Graph
`Intake -> Enrichment -> RAG -> Parse -> Classify -> Filter -> Orchestrator -> (Slack || Jira) -> Aggregate -> Respond`

### 5.2 Concurrency Model
- Graph-level parallelism: Slack and Jira run concurrently.
- Ticket-level parallelism: Jira ticket operations run with bounded concurrency of 5.
- Expected end-to-end time approximates `max(slack_branch, jira_branch)`.

## 6. Component Design
### 6.1 API Layer
- Endpoint: `POST /qa-intake`
- Inputs: multipart file, user_id, instruction
- Output: response contract with `trace_id`

### 6.2 Enrichment Node
- Purpose: normalize user instruction into a task contract.
- Retries: 1 retry for invalid JSON response.
- Output fields: `task_type`, branch flags, `confidence_threshold`.

### 6.3 RAG Retrieval Node
- Input: enriched task.
- Retrieval backend: Qdrant collection(s) for taxonomy, rules, and examples.
- Retrieval corpus: bug taxonomy, classification rules, historical examples.
- Strategy: semantic top-k retrieval plus rerank.
- Failure: if no usable context, stop classification path.

### 6.4 Classification Node
- Input: parsed issue + retrieved context.
- Output schema:
```json
{
  "issue_id": "string",
  "accuracy_related": true,
  "confidence": 0.82,
  "reason": "Incorrect numeric calculation"
}
```
- Processing: batch classification in chunks of 5-10 issues.

### 6.5 Filter Node
- Rule: keep issue when `accuracy_related` is true and confidence meets threshold.

### 6.6 Orchestrator Node
- Generates branch-specific instructions.
- Must not pass raw user instruction to tools unchanged.

### 6.7 Slack Branch
- Generate executive summary markdown.
- Post message via Slack API.
- Return `slack_url`.
- Retry policy: max 2 attempts.

### 6.8 Jira Branch
- Per issue: duplicate check then create-or-skip.
- Return created and duplicate references.
- Retry policy: max 2 attempts per ticket call.

### 6.9 Aggregation Node
- Merge Slack/Jira outputs.
- Preserve partial failure details in error list.

### 6.10 Observability Node
- LangSmith: node timing, prompts, tool calls, retries, routing.
- Langfuse: token usage, cost, latency distribution, duplicate rate.

## 7. Data Models
### 7.1 Global State
```json
{
  "request_id": "string",
  "parsed_issues": [],
  "enriched_task": {},
  "accuracy_definition": {},
  "classified_issues": [],
  "accuracy_issues": [],
  "slack_result": {},
  "jira_result": {},
  "errors": [],
  "metrics": {},
  "trace_id": "string"
}
```

### 7.2 Validation Rules
- `confidence` must be between 0 and 1.
- `reason` must be non-empty if `accuracy_related` is true.
- Every issue must have stable `issue_id`.

## 8. Failure Handling
### 8.1 Retry Policy
- LLM structured output: 1 retry.
- Slack API: 2 retries.
- Jira API: 2 retries per ticket.

### 8.2 Isolation Policy
- Slack branch failure must not block Jira branch completion.
- Jira per-ticket failure must not block other ticket attempts.
- Hard stop only for unrecoverable upstream failures (e.g., parsing or classification unavailable).

## 9. Performance and Scaling
### 9.1 Latency Budget
| Stage | Target |
| --- | --- |
| Enrichment | < 600 ms |
| RAG | < 300 ms |
| Classification (10 issues) | < 1.5 s |
| Slack branch | < 800 ms |
| Jira branch | < 2.0 s |
| End-to-end P95 | < 4.0 s |

### 9.2 Scalability Strategy
- Stateless API containers behind load balancer.
- Shared Qdrant cluster and secrets backend.
- User-level rate limiting and upload limits.

## 10. Security
- Secret storage for OpenAI, Slack, Jira tokens.
- Prompt and log scrubbing for sensitive fields.
- Upload file limits and mime/type validation.

## 11. Testing Strategy
- Unit: parsing, filtering, schema validation, duplicate checks.
- Integration: end-to-end with Slack/Jira mocks.
- Load: concurrent uploads and large issue sets.

## 12. Open Decisions
- Queue-based background execution rollout timing.
- Human approval threshold policy for low-confidence outputs.
