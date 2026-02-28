# AIA Diagrams (Mermaid)

This document provides Mermaid diagrams that summarize the full AIA system from the tutorial slides: architecture, tech stack, workflow, retrieval/action algorithms, data model, and reliability controls.

## 1) System Architecture (C4-style container view)

```mermaid
flowchart LR
  user[User] --> ui[Streamlit UI\n(Test UI)]
  user --> api[FastAPI API\n/qa-intake /upload /status]
  ui --> api

  api --> wf[Workflow Orchestrator\n(Node Pipeline)]
  wf --> llm[OpenAI LLM\nPlanning + Enrichment]
  wf --> qdrant[(Qdrant\nVector DB)]
  wf --> redis[(Redis\nCache + Status + Rate Limit)]
  wf --> mongo[(MongoDB\nConversation Memory)]

  wf --> jira[Jira Connector]
  wf --> telegram[Telegram Connector]

  jira --> jira_cloud[Jira Cloud]
  telegram --> telegram_api[Telegram Bot API]
```

## 2) Tech Stack Map

```mermaid
mindmap
  root((AIA Tech Stack))
    Backend
      FastAPI
      Python
      LangGraph-style nodes
      Pydantic contracts
    LLM
      OpenAI Chat API
      JSON normalization layer
    Retrieval
      Qdrant
      file_id filtering
    State
      Redis
        request status
        file upload status
        response cache
        rate limiting
      MongoDB
        conversations
        messages
        tool traces
    Integrations
      Jira REST API
      Telegram Bot API
      Slack (deferred/not supported runtime)
    UI
      Streamlit (testing)
```

## 3) End-to-End Runtime Flow

```mermaid
flowchart TD
  A[POST /qa-intake] --> B[Intake]
  B --> C[RAG Check\nfile_id exists?]
  C -- No --> F[Route Planning]
  C -- Yes --> D[RAG Query Enrichment]
  D --> E[RAG Retrieve + Compile Context]
  E --> F
  F --> G[Execute Actions]
  G --> H[Aggregate Final Response]
  H --> I[Store Conversation + Tool Logs]
  I --> J[Return response]
```

## 4) Upload + File Processing Pipeline

```mermaid
flowchart TD
  U1[POST /upload] --> U2[Generate file_id]
  U2 --> U3[Redis status: initiated]
  U3 --> U4[Parse file into chunks]
  U4 --> U5[Redis status: upload_complete]
  U5 --> U6[Redis status: embedding]
  U6 --> U7[Upsert chunks to Qdrant\npayload includes file_id]
  U7 --> U8[Redis status: saving_to_qdrant]
  U8 --> U9[Redis status: ready]
```

## 5) Action Execution Model (with dependency handling)

```mermaid
flowchart TD
  P[route_plan.action_plans] --> L{for each action}
  L --> M[Check depends_on success]
  M -- blocked --> N[Mark skipped]
  M -- ok --> O[Enrich params with request + RAG context]
  O --> O2[Precheck/sanitize params\n(chat_id, jira fields)]
  O2 --> Q{system}
  Q -- jira --> R[Jira client execute_action]
  Q -- telegram --> S[Telegram client execute_action]
  Q -- slack --> T[Return not supported]
  R --> V[Collect ActionResult]
  S --> V
  T --> V
  N --> V
  V --> W[Append errors + action_data]
```

## 6) RAG Retrieval Algorithm (file-scoped)

```mermaid
flowchart TD
  R1[Input instruction + file_id] --> R2[Build vector query text]
  R2 --> R3[Search Qdrant collections]
  R3 --> R4[Apply file_id filter]
  R4 --> R5[Collect top_k hits]
  R5 --> R6[Compile unique text lines]
  R6 --> R7[Pass compiled context to planner + action enrichment]
```

## 7) Routing Policy Rules (intent guardrails)

```mermaid
flowchart TD
  I1[Current user request] --> I2{file-scoped + telegram + no jira mention?}
  I2 -- yes --> I3[Keep telegram-only actions]
  I2 -- no --> I4{file-scoped + create jira tickets?}
  I4 -- yes --> I5{explicitly asked jira search/list/find?}
  I5 -- no --> I6[Drop jira_search_issues]
  I5 -- yes --> I7[Keep jira_search_issues]
  I4 -- no --> I8[Use normalized planner actions]
  I3 --> I9[Reconcile depends_on]
  I6 --> I9
  I7 --> I9
  I8 --> I9
```

## 8) Data Model (core records)

```mermaid
erDiagram
  CONVERSATION ||--o{ MESSAGE : contains
  CONVERSATION {
    string conversation_id
    string user_id
    string summary
    datetime updated_at
  }
  MESSAGE {
    string message_id
    string conversation_id
    string role
    string content
    string[] tools_used
    json meta
    datetime created_at
  }
  REQUEST_LOG {
    string request_id
    string conversation_id
    string user_id
    json request
    json response
    datetime created_at
  }
```

## 9) Cache + Status Strategy

```mermaid
flowchart LR
  Q1[qa-intake request] --> Q2[Rate limit counter in Redis]
  Q2 --> Q3[Response cache lookup]
  Q3 -- hit --> Q4[Return cached response]
  Q3 -- miss --> Q5[Run workflow]
  Q5 --> Q6{response has errors\nor failed action?}
  Q6 -- yes --> Q7[Do not cache]
  Q6 -- no --> Q8[Cache response with TTL]

  Q5 --> Q9[Write per-node status\nrequest_status:<id>]
  U[Upload flow] --> Q10[Write file status\nupload_status:<file_id>]
```

## 10) Telegram Safety Logic

```mermaid
flowchart TD
  T1[planner/enricher params] --> T2{telegram_send_message?}
  T2 -- no --> T9[pass through]
  T2 -- yes --> T3{trusted telegram_chat_id\nfrom API request?}
  T3 -- yes --> T4[set chat_id = trusted value]
  T3 -- no --> T5[remove model/planner chat_id]
  T5 --> T6[client fallback to TELEGRAM_DEFAULT_CHAT_ID]
  T4 --> T7[sendMessage]
  T6 --> T7
  T7 --> T8[ActionResult]
```

## 11) Jira Scope Migration Logic (Project -> Space)

```mermaid
flowchart TD
  J1[jira_create_issue requested] --> J2[Resolve scope mode]
  J2 --> J3{JIRA_SCOPE_MODE}
  J3 -- space --> J4[Use fields.space + space key]
  J3 -- project --> J5[Use fields.project + project key]
  J3 -- auto --> J6{space key exists?}
  J6 -- yes --> J4
  J6 -- no --> J5

  J4 --> J7[POST /rest/api/3/issue]
  J5 --> J7
  J7 --> J8{success?}
  J8 -- yes --> J9[Return created issue]
  J8 -- no --> J10[Toggle payload scope\nspace <-> project and retry]
  J10 --> J11{retry success?}
  J11 -- yes --> J9
  J11 -- no --> J12[Return structured failure + hints]
```

## 12) Jira Search Compatibility Fallback

```mermaid
sequenceDiagram
  participant WF as Workflow
  participant JC as Jira Client
  participant J as Jira API

  WF->>JC: jira_search_issues(params)
  JC->>J: POST /rest/api/3/search/jql
  alt success
    J-->>JC: 200
    JC-->>WF: success
  else fail
    JC->>J: GET /rest/api/3/search/jql
    alt success
      J-->>JC: 200
      JC-->>WF: success
    else fail
      JC->>J: POST /rest/api/3/search
      alt success
        J-->>JC: 200
        JC-->>WF: success
      else fail
        JC->>J: GET /rest/api/3/search
        J-->>JC: 4xx
        JC-->>WF: failed with error details
      end
    end
  end
```

## 13) Reliability Loop (Bug-to-Fix Lifecycle)

```mermaid
flowchart LR
  B1[Production/Test Failure] --> B2[Capture trace + symptom]
  B2 --> B3[Root cause analysis]
  B3 --> B4[Patch code + prompt + policy]
  B4 --> B5[Add regression tests]
  B5 --> B6[Update ERROR_LOG.md]
  B6 --> B7[Release + monitor]
  B7 --> B1
```

## 14) Deployment Topology (Docker Compose)

```mermaid
flowchart LR
  subgraph Compose
    API[aia-api]
    REDIS[aia-redis]
    MONGO[aia-mongo]
    QDRANT[aia-qdrant]
  end

  API --> REDIS
  API --> MONGO
  API --> QDRANT
  API --> OPENAI[OpenAI API]
  API --> JIRA[Jira Cloud]
  API --> TG[Telegram API]
```

## 15) Concurrency Mode Switch (Sequential vs Parallel)

```mermaid
flowchart TD
  A[execute_actions node] --> B{accept_parallel override?}
  B -- yes --> C[Use request value]
  B -- no --> D[Read ACCEPT_PARALLEL env]
  C --> E{parallel enabled?}
  D --> E
  E -- no --> F[Sequential executor]
  E -- yes --> G[Dependency-aware parallel executor]
```

## 16) Dependency-Layer Parallel Executor

```mermaid
flowchart TD
  S1[Pending actions] --> S2[Select ready set\\nall depends_on satisfied]
  S2 --> S3{ready set exists?}
  S3 -- yes --> S4[Execute ready actions concurrently]
  S4 --> S5[Store ActionResult + update statuses]
  S5 --> S1
  S3 -- no --> S6{pending actions remain?}
  S6 -- no --> S7[Finish]
  S6 -- yes --> S8[Mark unresolved dependency actions skipped]
```

## 17) Parallel-Eligible vs Sequential Scenarios

```mermaid
flowchart LR
  subgraph ParallelEligible
    P1[jira_create_issue]
    P2[telegram_send_message]
    P1 --- P2
    P3[depends_on=[]]
  end

  subgraph SequentialRequired
    S1[jira_search_issues] --> S2[telegram_send_message summary]
    S3[jira_create_issue] --> S4[jira_assign_issue]
  end
```

## 18) Automatic Grouping Strategy (Route -> Runtime)

```mermaid
sequenceDiagram
  participant RT as Route Planner
  participant EX as Executor

  RT->>EX: action_plans + depends_on
  EX->>EX: Build dependency graph
  EX->>EX: Compute execution layers
  alt parallel enabled
    EX->>EX: Run actions in same layer concurrently
    EX->>EX: Run next layer after prior layer completes
  else sequential mode
    EX->>EX: Run by route order
  end
  EX->>EX: Reorder outputs to original action index
```

## 19) Timing and UX Observability

```mermaid
flowchart TD
  U1[Streamlit request start] --> U2[Poll /qa-intake/{request_id}/status]
  U2 --> U3[Render current node state]
  U2 --> U4[Compute total runtime]
  U2 --> U5[Compute per-step durations\\nstarted_at -> finished_at]
  U5 --> U6[Show Detail per step]
```
