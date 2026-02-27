# AIA v1 Schemas and Prompt Templates

This folder contains implementation-ready contracts for AIA v1.

## Structure
- `schemas/`: JSON Schema contracts for request processing and outputs.
- `prompts/`: Prompt templates for enrichment, RAG retrieval, routing, classification, and branch execution.

## Suggested Runtime Order
1. Validate intake request.
2. Run enrichment prompt and validate `enriched_task`.
3. Build RAG query from `enriched_task`.
4. Retrieve context from Qdrant and package context.
5. Classify issues using context and validate each classification object.
6. Filter by confidence threshold.
7. Route with orchestrator prompt.
8. Execute Slack and Jira branches in parallel.
9. Validate final API response before returning.

## Files to Start With
- `schemas/enriched_task.schema.json`
- `schemas/classification_output.schema.json`
- `schemas/final_response.schema.json`
- `prompts/enrichment.system.md`
- `prompts/rag-query-builder.system.md`
- `prompts/orchestrator-routing.system.md`
