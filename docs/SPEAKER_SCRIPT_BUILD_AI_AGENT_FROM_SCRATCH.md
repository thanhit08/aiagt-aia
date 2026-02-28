# Speaker Script - Build an AI Agent From Scratch (Beginner)

Use this as talk track per slide in `BUILD_AI_AGENT_FROM_SCRATCH_SLIDES.md`.

## Slide 1 - Title
"Today we will build an AI agent from scratch, but more importantly, we will show what it takes to make it work reliably in a real system, not only in a toy demo."

## Slide 2 - Why Build This?
"Users want to ask in natural language and get actions done, not just text answers. Our goal is to move from chatbot behavior to workflow automation behavior."

## Slide 3 - What This System Does
"The system accepts requests, optionally uses uploaded files for retrieval, plans actions, executes tools like Jira and Telegram, and returns a traceable response."

## Slide 4 - High-Level Architecture
"Think in layers: API, workflow orchestration, state and memory, retrieval, and tool adapters. Streamlit is only the test UI layer."

## Slide 5 - Current Workflow
"This is the implemented node flow: intake, RAG decision, RAG query enrichment, retrieval, route planning, action execution, and final aggregation."

## Slide 6 - Why This Workflow Matters
"We separated concerns to reduce failure modes: retrieval is not mixed with action planning, and each step is observable and testable."

## Slide 7 - Data & Integrations
"Redis handles short-lived state and limits, Mongo handles long-term conversation memory, and Qdrant stores file chunks by file_id for scoped retrieval."

## Slide 8 - Streamlit Role
"The UI is for testing and visibility. It helps verify timing and routing, but all business logic remains in backend nodes."

## Slide 9 - Bug #1 Validation 500
"First critical lesson: never trust raw LLM JSON. Normalize first, validate second, and always provide fallback objects."

## Slide 10 - Bug #2 Unsupported Actions
"Second lesson: use a fixed action catalog. If the model invents names, map aliases or reject safely."

## Slide 11 - Bug #3 Wrong Route Plan
"We saw Jira search being added even when not requested. We fixed this with intent-policy rules and dependency reconciliation."

## Slide 12 - Bug #4 Telegram chat routing
"Routing parameters like chat_id must be trusted config, not planner-generated values."

## Slide 13 - Bug #5 Jira API compatibility
"Provider APIs vary by tenant. We added endpoint and method fallbacks to keep execution resilient."

## Slide 14 - Bug #6 Jira space/project migration
"We implemented dual compatibility for Jira scope migration so teams can move safely without breaking ticket creation."

## Slide 15 - Bug #7 Cache issue
"Failed outputs should not be cached. Otherwise users keep getting stale failures after fixes."

## Slide 16 - Bug #8 Workflow status UX
"If status events are coarse, users lose trust. We switched to deterministic step status updates."

## Slide 17 - Engineering Practices
"The pattern is consistent: reproduce, root cause, patch, add regression test, and update error docs."

## Slide 18 - Minimal Local Run
"This is the practical path to validate locally: upload, intake with file_id, poll status, and verify tool outputs."

## Slide 19 - Beginner Takeaways
"Treat LLM outputs as untrusted inputs, keep flows observable, and design for failures before happy paths."

## Slide 20 - V2 Ideas
"These are natural next steps: approval gates, per-tenant capabilities, richer observability, and load testing."

## Slide 21 - Deep Dive Concurrency
"We introduced automatic grouping: parallel inside dependency layers, sequential across layers."

## Slide 22 - Why Performance Improves
"This gives lower latency without losing safety, because dependencies still control order."

## Slide 23 - Automatic Switch Strategy
"Route provides action graph, executor computes layers, runs based on mode, and preserves deterministic result order."

## Slide 24 - Final Message
"Production AI agents are systems engineering: workflow, contracts, policy, integration reliability, and observability."
