# AIA v1 Schemas and Prompt Templates

This folder contains implementation-ready contracts for general query orchestration with Jira/Slack action catalogs.

## Supported Interaction Pattern
- User asks any question
- File uploaded via `/upload` gets `file_id`
- `/qa-intake` can include `file_id` for file-scoped retrieval
- Optional conversation_id for multi-turn continuity
- Enrichment generates `action_plans[]`
- Optional RAG retrieval
- RAG retrieval supports filter by `file_id`
- Conversation summary + recent messages injected as context
- Route planner validates actions
- Executors run Jira/Slack actions
- Aggregator returns answer + action results

## Key Contracts
- `schemas/enriched_task.schema.json`
- `schemas/route_plan.schema.json`
- `schemas/final_response.schema.json`

## Key Prompts
- `prompts/enrichment.system.md`
- `prompts/orchestrator-routing.system.md`
- `prompts/jira-ticket.system.md`
- `prompts/slack-summary.system.md`

## Compatibility Note
Legacy placeholder variable names may remain in some prompt templates to keep current code paths stable until executor refactor is complete.

## Memory Strategy
- Selected strategy: rolling summary + recent message window.
- Long history is compacted into summary in MongoDB when threshold is exceeded.
