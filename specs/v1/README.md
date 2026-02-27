# AIA v1 Schemas and Prompt Templates

This folder contains implementation-ready contracts for general query orchestration with Jira/Slack action catalogs.

## Supported Interaction Pattern
- User asks any question
- Optional file/context provided
- Enrichment generates `action_plans[]`
- Optional RAG retrieval
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
