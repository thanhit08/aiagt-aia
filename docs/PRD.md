# Product Requirements Document (PRD)

## 1. Document Control
- Product: AI Agent Toolkit (AIA)
- Owner: Product Manager
- Primary Audience: Product, Engineering, QA
- Status: Draft for implementation
- Last Updated: 2026-02-27

### 1.1 Update Policy
- This document is the source of truth for product scope, user value, and acceptance criteria.
- Engineering implementation details are defined in `docs/TDD.md`.
- Visual architecture diagrams are defined in `docs/diagram.md`.

## 2. Product Summary
AIA is a general-purpose AI orchestration system that can:
- Answer arbitrary user questions.
- Accept optional file uploads for context.
- Decide at runtime whether to retrieve knowledge from RAG.
- Execute Jira and Slack actions inferred from user intent.

## 3. Problem Statement
Users need one endpoint that can answer questions and perform operational actions across tools. Current pain points:
- Natural-language requests mix search/read/write/update intentions.
- Files are optional and should not be required for tool actions.
- Jira/Slack actions should be inferred safely and executed consistently.
- Action outcomes must be observable and auditable.

## 4. Goals and Non-Goals
### 4.1 Goals
- G1: Support any user question through one endpoint.
- G2: Support optional file input and optional RAG.
- G3: Infer action intent and parameters from query.
- G4: Support full Jira and Slack action catalog via connector abstraction.
- G5: Provide safe execution controls for destructive actions.
- G6: Preserve observability and deterministic response contracts.

### 4.2 Non-Goals (Current Phase)
- Autonomous long-horizon planning without explicit user intent.
- Unbounded multi-step workflows without guardrails.

## 5. Users
- Engineers, QA, support, technical PMs, engineering managers.

## 6. Scope
### 6.1 In Scope
- Unified query endpoint.
- Optional file upload.
- Request enrichment.
- Optional RAG retrieval.
- Jira action execution (read/write/update/search/transition/comment).
- Slack action execution (post/update/thread/search/channel/member actions).
- Unified response with action results and trace metadata.

### 6.2 Out of Scope (Current Phase)
- Autonomous multi-day workflow execution.
- Cross-tenant governance dashboards.

## 7. Functional Requirements
- FR-01 Unified Intake: accept query + optional structured context + optional file.
- FR-02 Enrichment: infer user intent, target systems, and action plans.
- FR-03 Action Catalog: support all configured Jira and Slack actions through a registry.
- FR-04 Dynamic Routing: generate per-system action plans from user query.
- FR-05 Optional RAG: retrieve from Qdrant only when needed.
- FR-06 Core Answer: always return a natural-language answer.
- FR-07 Jira Actions: execute catalog actions and return structured results.
- FR-08 Slack Actions: execute catalog actions and return structured results.
- FR-09 Parallel Execution: execute independent actions in parallel.
- FR-10 Safety Controls: require confirmation policy for destructive/high-impact actions.
- FR-11 Observability: trace all routing decisions and external calls.
- FR-12 Graceful Degradation: partial tool failures must not drop core answer.

## 8. Jira and Slack Action Catalog
### 8.1 Jira Action Types
- `jira_search_issues`
- `jira_get_issue`
- `jira_create_issue`
- `jira_update_issue`
- `jira_transition_issue`
- `jira_add_comment`
- `jira_assign_issue`
- `jira_link_issues`
- `jira_bulk_update`

### 8.2 Slack Action Types
- `slack_post_message`
- `slack_update_message`
- `slack_reply_in_thread`
- `slack_search_messages`
- `slack_get_channel_history`
- `slack_create_channel`
- `slack_archive_channel`
- `slack_invite_users`
- `slack_add_reaction`

## 9. Non-Functional Requirements
- NFR-01 Latency: P95 under 4 seconds for single-action requests.
- NFR-02 Reliability: bounded retries and branch isolation.
- NFR-03 Scalability: stateless API horizontal scaling.
- NFR-04 Security: per-action authorization, secret management, redaction.
- NFR-05 Auditability: every action includes request correlation IDs.

## 10. Data Contracts
### 10.1 Enriched Task (Example)
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
      "risk_level": "low"
    },
    {
      "system": "slack",
      "action": "slack_post_message",
      "params": {"channel": "#eng", "text": "Posted search summary"},
      "risk_level": "low"
    }
  ]
}
```

### 10.2 Final Response (Example)
```json
{
  "request_id": "string",
  "answer": "string",
  "trace_id": "string",
  "action_results": [
    {"system": "jira", "action": "jira_search_issues", "status": "success", "data": {}},
    {"system": "slack", "action": "slack_post_message", "status": "success", "data": {"url": "..."}}
  ],
  "errors": []
}
```

## 11. Acceptance Criteria
- AC-01 User can ask read/query tasks (e.g., "find issues assigned to me in Jira").
- AC-02 User can ask write tasks (e.g., "create Jira bug for login issue").
- AC-03 User can trigger Slack actions (post/update/thread/search/channel operations).
- AC-04 Multiple actions across Jira/Slack execute with deterministic ordering and parallelization where safe.
- AC-05 High-risk actions follow safety policy.
- AC-06 Core answer is always returned even with partial action failures.

## 12. Demo Pass Criteria
- D-01 Jira assignee search.
- D-02 Jira bug create for login issue.
- D-03 Slack message post + update.
- D-04 Combined Jira + Slack request in one query.
- D-05 Trace log includes action plan and outcomes.

## 13. Traceability to TDD
Implementation mapping is defined in `docs/TDD.md` section "PRD to TDD Traceability Matrix".
