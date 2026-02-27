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
