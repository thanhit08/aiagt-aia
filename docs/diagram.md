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
