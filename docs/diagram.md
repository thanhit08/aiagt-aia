# Architecture Diagrams Addendum

## 1. Usage
- This document is diagrams-only.
- Canonical engineering behavior is defined in `docs/TDD.md`.
- Canonical product scope is defined in `docs/PRD.md`.

## 2. System Context (C4 Level 1)
```mermaid
flowchart LR
    User[Engineer or QA User]
    AIA[Accuracy Intelligence Agent]
    Slack[Slack Workspace]
    Jira[Jira Cloud]
    OpenAI[OpenAI API]
    LangSmith[LangSmith]
    Langfuse[Langfuse]

    User --> AIA
    AIA --> Slack
    AIA --> Jira
    AIA --> OpenAI
    AIA --> LangSmith
    AIA --> Langfuse
```

## 3. Container View (C4 Level 2)
```mermaid
flowchart TB
    Client[Web or CLI Client]

    subgraph Backend
      API[FastAPI Service]
      Graph[LangGraph Engine]
      RAG[Qdrant Vector DB]
      Parser[File Parser]
      SlackAgent[Slack Branch]
      JiraAgent[Jira Branch]
    end

    OpenAI[OpenAI GPT-4o]
    Slack[Slack API]
    Jira[Jira API]
    LangSmith[LangSmith]
    Langfuse[Langfuse]

    Client --> API
    API --> Graph
    Graph --> Parser
    Graph --> RAG
    Graph --> SlackAgent
    Graph --> JiraAgent
    Graph --> OpenAI
    SlackAgent --> Slack
    JiraAgent --> Jira
    Graph --> LangSmith
    Graph --> Langfuse
```

## 4. End-to-End Sequence
```mermaid
sequenceDiagram
    participant User
    participant API
    participant Graph
    participant RAG
    participant LLM
    participant Slack
    participant Jira

    User->>API: Upload QA file
    API->>Graph: Start workflow
    Graph->>LLM: Enrichment prompt
    LLM-->>Graph: Structured task
    Graph->>RAG: Retrieve accuracy definition
    RAG-->>Graph: Context package
    Graph->>LLM: Classify issues
    LLM-->>Graph: Classification output

    par Parallel branches
      Graph->>Slack: Post summary
      Slack-->>Graph: Slack URL
    and
      Graph->>Jira: Create tickets
      Jira-->>Graph: Ticket URLs
    end

    Graph-->>API: Aggregated result
    API-->>User: JSON response
```

## 5. RAG Pipeline
```mermaid
flowchart TD
    A[Enriched Task] --> B[Query Generator]
    B --> C[Embedding Model]
    C --> D[Qdrant Search]
    D --> E[Top-K Chunks]
    E --> F[Rerank]
    F --> G[Context Packager]
    G --> H[Classification Prompt]
```

## 6. Concurrency Model
```mermaid
flowchart TD
    A[Accuracy Issues Ready] --> B1[Slack Branch]
    A --> B2[Jira Branch]

    B1 --> C1[Generate Summary]
    C1 --> D1[Post to Slack]

    B2 --> C2[Duplicate Check]
    C2 --> D2[Create Tickets Async]
```

```mermaid
flowchart LR
    A[Accuracy Issues] --> T1[Ticket 1]
    A --> T2[Ticket 2]
    A --> T3[Ticket 3]
    A --> Tn[Ticket N]
```

## 7. State Machine
```mermaid
stateDiagram-v2
    [*] --> Enrichment
    Enrichment --> Retrieval
    Retrieval --> Classification
    Classification --> Filter
    Filter --> Orchestrate
    Orchestrate --> SlackBranch
    Orchestrate --> JiraBranch
    SlackBranch --> Aggregate
    JiraBranch --> Aggregate
    Aggregate --> Complete
    Complete --> [*]
```

## 8. Observability Topology
```mermaid
flowchart LR
    Graph[LangGraph Runtime] --> Trace[LangSmith Traces]
    Graph --> Metrics[Langfuse Metrics]
```

## 9. Failure Isolation
```mermaid
flowchart TD
    Start[Parallel Execution] --> SlackOK[Slack Success]
    Start --> JiraFail[Jira Ticket Failure]
    JiraFail --> Retry[Retry]
    Retry --> FailStill[Still Failing]
    FailStill --> Continue[Record Error and Continue]
```

## 10. Deployment Topology
```mermaid
flowchart TB
    LB[Load Balancer] --> API1[API Instance 1]
    LB --> API2[API Instance 2]

    API1 --> OpenAI[OpenAI]
    API2 --> OpenAI

    API1 --> Slack[Slack]
    API2 --> Slack

    API1 --> Jira[Jira]
    API2 --> Jira

    API1 --> Qdrant[Qdrant]
    API2 --> Qdrant

    API1 --> LangSmith[LangSmith]
    API2 --> LangSmith

    API1 --> Langfuse[Langfuse]
    API2 --> Langfuse
```
