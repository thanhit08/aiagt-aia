# Architecture Diagrams Addendum

## 1. System Context
```mermaid
flowchart LR
    User --> API[AIA FastAPI]
    API --> OpenAI
    API --> Qdrant
    API --> Redis
    API --> MongoDB
    API --> Jira
    API --> Telegram
```

## 2. Main Request Flow (`/qa-intake`)
```mermaid
sequenceDiagram
    participant U as User
    participant A as API
    participant R as Redis
    participant M as Mongo
    participant G as Graph
    participant Q as Qdrant
    participant J as Jira
    participant T as Telegram

    U->>A: POST /qa-intake (instruction, optional file_id, conversation_id)
    A->>R: rate limit check
    A->>R: response cache lookup
    A->>M: load conversation summary + recent messages
    A->>G: invoke workflow
    G->>Q: optional retrieval (filter by file_id)
    G->>J: optional jira action(s)
    G->>T: optional telegram action(s)
    G-->>A: answer + action_results
    A->>M: persist user/assistant messages + request/response
    A->>M: compact history (summary + recent window)
    A->>R: cache response
    A-->>U: final response
```

## 2.1 Workflow Orchestrator Flowchart
```mermaid
flowchart TD
    I[Intake] --> C{RAG Check}
    C -- yes --> QE[RAG Query Enrichment]
    QE --> RG[RAG Retrieval]
    C -- no --> RT[Route Planning]
    RG --> RT
    RT --> EX[Execute Actions]
    EX --> AG[Aggregate]
    AG --> D[Done]
```

## 2.2 Workflow Orchestrator Sequence
```mermaid
sequenceDiagram
    participant A as API
    participant O as Orchestrator
    participant L as LLM
    participant Q as Qdrant
    participant X as Tool Adapters

    A->>O: invoke workflow(state)
    O->>O: intake + rag_check
    alt rag_required
      O->>L: rag query enrichment
      L-->>O: query spec
      O->>Q: retrieve with file_id filter
      Q-->>O: rag_context
    end
    O->>L: route/enrichment
    L-->>O: action_plans
    O->>X: execute actions
    X-->>O: action_results
    O->>O: aggregate
    O-->>A: final response
```

## 3. Upload Flow (`/upload`)
```mermaid
sequenceDiagram
    participant U as User
    participant A as API
    participant R as Redis
    participant Q as Qdrant

    U->>A: POST /upload (file)
    A->>R: set file_meta:{file_id}
    A->>R: file_status initiated
    A->>R: file_status upload_complete
    A->>R: file_status embedding
    A->>R: file_status saving_to_qdrant
    A->>Q: upsert chunks (payload.file_id)
    A->>R: file_status ready
    A-->>U: file_id
```

## 4. Upload Status/Metadata Endpoints
```mermaid
flowchart LR
    Client --> S1[GET /upload/{file_id}/status]
    Client --> S2[GET /upload/{file_id}]
    S1 --> Redis
    S2 --> Redis
```

## 4.1 Redis Sequence (Rate Limit, Cache, Status)
```mermaid
sequenceDiagram
    participant A as API
    participant R as Redis

    A->>R: rate limit increment with TTL
    A->>R: response cache lookup
    alt cache miss
      A->>R: set request_status running
      A->>R: update request_status per node
      A->>R: cache final response (success only)
    else cache hit
      R-->>A: cached response
    end
```

## 4.2 MongoDB Sequence (Conversation Memory)
```mermaid
sequenceDiagram
    participant A as API
    participant M as MongoDB
    participant L as LLM

    A->>M: load conversation context
    M-->>A: summary + recent messages
    A->>M: append user message
    A->>M: append assistant message + tools used
    A->>M: log request/response
    A->>M: maybe compact history
    alt threshold exceeded
      A->>L: summarize older history
      L-->>A: summary text
      A->>M: store compacted summary
    end
```

## 5. Action Execution Algorithm (Sequential vs Parallel)
```mermaid
flowchart TD
    A[route_plan.action_plans] --> B{ACCEPT_PARALLEL or accept_parallel?}
    B -- no --> C[Sequential loop]
    B -- yes --> D[Dependency-layer parallel executor]
    C --> E[Run action i]
    E --> F{depends_on satisfied?}
    F -- no --> G[mark skipped]
    F -- yes --> H[execute action]
    H --> I[store ActionResult]
    I --> E
    D --> J[Find ready actions\\nall depends_on succeeded]
    J --> K[Run ready set concurrently]
    K --> L[Collect ActionResult]
    L --> M[Update dependency state]
    M --> J
```

## 5.1 Action Execution Sequence
```mermaid
sequenceDiagram
    participant E as Executor
    participant L as LLM (Param Enrichment)
    participant J as Jira Client
    participant T as Telegram Client

    E->>E: read action_plans + depends_on
    loop each ready layer
      E->>E: pick ready actions
      par action i
        E->>L: enrich params(action i)
        L-->>E: enriched params
        E->>J: execute (if jira)
        J-->>E: ActionResult
      and action j
        E->>L: enrich params(action j)
        L-->>E: enriched params
        E->>T: execute (if telegram)
        T-->>E: ActionResult
      end
      E->>E: update dependency state
    end
    E->>E: sort results to original route order
```

## 6. Parallel-Eligible vs Sequential Patterns
```mermaid
flowchart LR
    subgraph ParallelEligible
      P1[jira_create_issue]
      P2[telegram_send_message]
      P1 --- P2
    end

    subgraph SequentialRequired
      S1[jira_search_issues] --> S2[telegram_send_message summary]
      S3[jira_create_issue] --> S4[jira_assign_issue]
    end
```

## 7. Automatic Grouping by Dependency Layers
```mermaid
flowchart TD
    A[route_plan.action_plans] --> B[Build dependency graph]
    B --> C[Compute layer 0: no deps]
    C --> D[Compute next layers: deps satisfied by earlier layers]
    D --> E{parallel mode enabled?}
    E -- no --> F[Run all actions sequentially by plan order]
    E -- yes --> G[Run each layer sequentially\\nRun actions within layer in parallel]
    G --> H[Merge results in original plan order]
```

## 8. Enrichment Flows
### 8.0 Retrieval Sequence
```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant L as LLM (RAG Query Enrichment)
    participant Q as Qdrant

    O->>L: request rag query spec (instruction + file_id)
    L-->>O: rag_query_spec
    O->>Q: search with file_id filter
    Q-->>O: retrieval hits
    O->>O: compile rag context
```

### 8.1 RAG Query Enrichment
```mermaid
flowchart TD
    R1[raw_instruction + file_id] --> R2[LLM rag-query-builder]
    R2 --> R3[Normalize query spec]
    R3 --> R4[Ensure uploaded_files collection included]
    R4 --> R5[rag_query_spec ready]
```

### 8.2 Action Parameter Enrichment
```mermaid
flowchart TD
    P1[action + params] --> P2[LLM param enrichment with request + rag context]
    P2 --> P3[merge params]
    P3 --> P4[sanitize protected fields]
    P4 --> P5[action-specific precheck]
    P5 --> P6[execute tool]
```

### 8.3 Enrichment Sequence
```mermaid
sequenceDiagram
    participant EX as Executor
    participant LLM as LLM
    participant V as Validator
    participant T as Tool

    EX->>LLM: enrich params(request + rag context + base params)
    LLM-->>EX: enriched params patch
    EX->>V: sanitize and validate
    alt valid
      V-->>EX: executable params
      EX->>T: execute action
      T-->>EX: ActionResult
    else invalid
      V-->>EX: precheck error result
    end
```
