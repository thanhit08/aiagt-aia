# Architecture Diagrams Addendum

## 1. Usage
- This document is diagrams-only.
- Canonical behavior is defined in `docs/TDD.md`.

## 2. System Context
```mermaid
flowchart LR
    User[User] --> AIA[AIA Orchestrator]
    AIA --> OpenAI[OpenAI]
    AIA --> Qdrant[Qdrant]
    AIA --> Redis[Redis]
    AIA --> Mongo[MongoDB]
    AIA --> Jira[Jira API]
    AIA --> Slack[Slack API]
    AIA --> Obs[LangSmith/Langfuse]
```

## 3. Container View
```mermaid
flowchart TB
    Client[Client/Postman/curl] --> API[FastAPI]
    API --> Graph[Workflow Engine]
    Graph --> Enrich[Intent Enrichment]
    Graph --> RAG[Optional Retrieval]
    Graph --> Synth[Answer Synthesis]
    Graph --> Planner[Action Planner]
    Planner --> Exec[Action Executor]
    Graph --> Cache[Redis Cache/Rate Limit]
    Graph --> Memory[Conversation Memory Manager]
    Memory --> Mongo[MongoDB]
    Exec --> Jira[Jira Connector]
    Exec --> Slack[Slack Connector]
```

## 4. End-to-End Sequence
```mermaid
sequenceDiagram
    participant U as User
    participant A as API
    participant G as Graph
    participant L as LLM
    participant R as Qdrant
    participant M as Mongo
    participant J as Jira
    participant S as Slack

    U->>A: instruction (+ optional file)
    A->>G: start
    G->>M: load summary + recent messages
    G->>L: enrichment
    L-->>G: action_plans + route metadata

    alt requires_rag
      G->>R: retrieve context
      R-->>G: context
    end

    G->>L: synthesize answer
    L-->>G: answer

    par execute independent actions
      G->>J: jira action(s)
      J-->>G: result(s)
    and
      G->>S: slack action(s)
      S-->>G: result(s)
    end

    G-->>A: answer + action_results + errors
    G->>M: store user/assistant messages + tools used + request/response
    G->>M: compact history (summary + recent window) if needed
    A-->>U: final response
```

## 5. Action Planner and DAG
```mermaid
flowchart TD
    A[Enriched Intent] --> B[Action Registry Validation]
    B --> C[Build Action DAG]
    C --> D[Parallel Ready Actions]
    D --> E[Execute]
    E --> F[Collect Results]
```

## 6. Failure Isolation
```mermaid
flowchart TD
    A[Answer Ready] --> B1[Jira Action]
    A --> B2[Slack Action]
    B1 --> C1[Success/Fail]
    B2 --> C2[Success/Fail]
    C1 --> D[Aggregate]
    C2 --> D
    D --> E[Return Answer + Partial Results]
```

## 7. Deployment Topology
```mermaid
flowchart TB
    LB[Load Balancer] --> API1[API Instance 1]
    LB --> API2[API Instance 2]
    API1 --> OpenAI
    API2 --> OpenAI
    API1 --> Qdrant
    API2 --> Qdrant
    API1 --> Redis
    API2 --> Redis
    API1 --> Mongo
    API2 --> Mongo
    API1 --> Jira
    API2 --> Jira
    API1 --> Slack
    API2 --> Slack
    API1 --> Obs[LangSmith/Langfuse]
    API2 --> Obs
```
