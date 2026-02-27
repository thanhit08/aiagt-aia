# Error Log

## 2026-02-27 - `/qa-intake` returns 500 during enrichment validation

### Symptom
- Endpoint: `POST /qa-intake`
- Result: `500 Internal Server Error`
- Failure point: enrichment node validation (`EnrichedTask.model_validate(...)`)

### Root Cause
The LLM enrichment response did not match the strict `EnrichedTask` schema:
- `task_type` returned unsupported value (`issue_summary`)
- `output_tone` was missing
- `action_plans` used `platform` instead of `system`
- `depends_on` was not consistently `list[str]` (sometimes string or null)
- extra fields were included and rejected by schema (`extra="forbid"`)

### Why This Happened
- Runtime depends on model-generated JSON, but model outputs are probabilistic and may drift from schema.
- Validation was strict (correct) but no normalization/sanitization layer existed before schema validation.

### Resolution
- Added normalization layer in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py)
- Enrichment node now normalizes raw LLM output before validating against `EnrichedTask`.
- Normalization rules include:
  - task type alias mapping (`issue_summary` -> `summarization`)
  - default `output_tone` -> `neutral` when missing/invalid
  - `platform` -> `system` mapping and lowercase normalization
  - `depends_on` normalization to `list[str]`
  - filtering/dropping invalid/extra action plan fields
- Added tests in [tests/test_enrichment_normalization.py](E:/2026/AIA/tests/test_enrichment_normalization.py)

### Prevention
- Keep strict Pydantic schemas, but always add a normalization boundary for LLM outputs.
- Add regression tests for known malformed model outputs.
- Keep prompt instructions explicit, but do not rely on prompt-only enforcement.

### Verification
- Local compile checks passed for updated modules.
- Normalization test cases added for malformed outputs.

## 2026-02-27 - `/qa-intake` still 500 with `find_and_send_summary` and malformed action plans

### Symptom
- Endpoint: `POST /qa-intake`
- Result: `500 Internal Server Error`
- Validation errors included:
  - `task_type='find_and_send_summary'` (not allowed by schema)
  - missing `output_tone`
  - `platform` present instead of `system`
  - `depends_on` as `null` or `string`

### Root Cause
- Runtime enrichment path still validated raw LLM JSON directly in `enrichment_node`.
- Route planning also trusted raw LLM output shape.
- Existing normalization logic was not wired into node execution.

### Why This Happened
- LLM output shape drift is expected over time (new labels like `find_and_send_summary`).
- Validation-first without a normalization boundary causes hard failures.

### Resolution
- Wired normalization into [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - `enrichment_node` now normalizes then validates.
  - `route_node` now normalizes then validates.
  - both nodes now use safe fallback objects instead of raising 500.
- Expanded alias handling in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py):
  - `find_and_send_summary` -> `tool_orchestration`
- Added route normalization utility and regression tests in [tests/test_enrichment_normalization.py](E:/2026/AIA/tests/test_enrichment_normalization.py).

### Prevention
- Treat all LLM JSON as untrusted input.
- Normalize at every LLM boundary (enrichment and routing), not only one node.
- Keep fallback-safe defaults so user requests still return 200 with structured warnings.

### Verification
- Compiled updated modules successfully.
- Added tests covering malformed enrichment and route payload structures.

## 2026-02-27 - Actions fail with `Unsupported ... action` for `search_issues`/`send_summary`

### Symptom
- Endpoint: `POST /qa-intake`
- API returned `200`, but all action executions failed.
- Example failures:
  - `Unsupported Jira action: search_issues`
  - `Unsupported Telegram action: send_summary`
- Response contained `"cached": true`.

### Root Cause
- LLM produced semantically correct but non-canonical action IDs.
- Executors only support strict catalog IDs (`jira_search_issues`, `telegram_send_message`, etc.).
- Cached response returned a previously failed action plan.

### Why This Happened
- Prompt asks for valid catalog actions, but model still sometimes emits short aliases.
- No action-ID canonicalization layer existed before action execution.
- Cache served old output for same request payload.

### Resolution
- Added action alias canonicalization in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py):
  - Jira: `search_issues`/`find_issues_assigned_to_user` -> `jira_search_issues`
  - Telegram: `send_summary`/`send_message` -> `telegram_send_message`
  - Similar normalization for Slack actions.
- Added regression coverage in [tests/test_enrichment_normalization.py](E:/2026/AIA/tests/test_enrichment_normalization.py).

### Prevention
- Keep a canonical action registry and normalize model action IDs before execution.
- For debugging, bypass cache by changing request text or waiting for TTL.

### Verification
- Compile checks passed after alias normalization changes.

## 2026-02-27 - Real service execution failures (Jira 410, Telegram 400)

### Symptom
- Endpoint: `POST /qa-intake`
- Action names were canonical, but execution failed:
  - Jira: `http_410` with message to migrate from `/rest/api/3/search` to `/rest/api/3/search/jql`
  - Telegram: `400 Bad Request` from `sendMessage`

### Root Cause
- Jira client used deprecated endpoint `/rest/api/3/search`.
- Telegram client raised on HTTP status before parsing Telegram error body, hiding actionable cause (`chat not found`, `bot blocked`, etc.).

### Why This Happened
- Upstream API behavior changed/deprecated on Jira tenant.
- Error handling path prioritized transport exceptions over provider-specific diagnostics.

### Resolution
- Updated Jira search action to prefer `/rest/api/3/search/jql` with fallback to `/rest/api/3/search`.
- Updated Telegram client to parse non-2xx responses and return provider error descriptions with hints.
- Added structured helper for safe JSON parsing and Telegram-specific hinting.

### Prevention
- Prefer provider current endpoints; keep fallback for cross-tenant compatibility.
- Avoid `raise_for_status()` when provider error payload contains required diagnostics.

### Verification
- Local compile check passed for updated client module.

## 2026-02-27 - Jira search rejected unbounded JQL and Telegram rejected empty message text

### Symptom
- Endpoint: `POST /qa-intake`
- Action errors:
  - Jira `jira_search_issues`: `http_400` with `Unbounded JQL queries are not allowed`
  - Telegram `telegram_send_message`: `http_400` with `message text is empty`

### Root Cause
- Model-generated Jira params did not include sufficiently bounded JQL for tenant policy.
- Telegram action params contained empty/whitespace `text`.

### Why This Happened
- Action-name normalization existed, but action-parameter normalization was still weak.
- Executor trusted LLM params without enforcing minimum safe defaults.

### Resolution
- Added action param normalization in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py):
  - for `jira_search_issues`, enforce bounded default JQL and `maxResults`
  - for `telegram_send_message`, enforce non-empty fallback text
- Added runtime guard in [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py) to inject answer text when Telegram message text is empty.
- Added failed action propagation into `errors` array for clearer diagnostics.
- Added regression tests in [tests/test_enrichment_normalization.py](E:/2026/AIA/tests/test_enrichment_normalization.py).

### Prevention
- Normalize action parameters per action type before execution.
- Keep tenant-policy-aware defaults (bounded JQL, capped result size).
- Ensure every action failure also appears in top-level `errors`.

### Verification
- Local compile checks passed after updates.

## 2026-02-27 - File-scoped query routed to invalid Jira pseudo-actions

### Symptom
- User asks: "Get all issues in the file related to accuracy and send to Telegram channel"
- Returned actions were:
  - `jira_search_issues_in_jira`
  - `jira_send_summary_to_telegram`
- Both failed as unsupported actions.

### Root Cause
- LLM generated pseudo-action names not in the action catalog.
- System inference defaulted unknown/missing system to Jira.
- Route plan did not filter out Jira actions for file-scoped requests that did not ask for Jira.

### Why This Happened
- Model output mixed semantic intent and transport target in action IDs.
- Canonicalization covered common aliases but not these composed pseudo-actions.

### Resolution
- Extended action alias normalization in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py):
  - `jira_search_issues_in_jira` -> `jira_search_issues`
  - `jira_send_summary_to_telegram` -> `telegram_send_message`
- Improved system inference from action names (`telegram`/`slack`/`jira` keyword detection).
- Added action-prefix-based system correction (`telegram_*` -> `telegram`, etc.).
- Added intent filter in [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py) to drop Jira actions for file-scoped requests unless user explicitly mentions Jira.

### Prevention
- Keep canonicalization dictionary for cross-system pseudo-actions.
- Apply intent-level routing guards after LLM route generation.
- Add regression tests for file-scoped routing behavior.

### Verification
- Compile checks passed and route filter tests added.

## 2026-02-27 - File request sent to Telegram without RAG retrieval

### Symptom
- User uploaded a file and asked: "Get all issues in the file related to accuracy and send to Telegram channel"
- Response executed Telegram send directly with generic text and did not reflect file-grounded retrieval.

### Root Cause
- `requires_rag` from enrichment was false for a file-scoped query.
- RAG node was therefore skipped.
- Telegram message used fallback text rather than answer-based summary.

### Why This Happened
- Enrichment output was trusted for `requires_rag` even when file scope strongly implied retrieval.
- Telegram param normalization injected static fallback text too early.

### Resolution
- Added force-RAG heuristic in [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - when `file_id` is provided and request is file/content scoped, set `requires_rag = true`.
- Removed static telegram fallback text injection in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py) so execution layer can use answer text.
- Existing runtime guard in `execute_actions_node` fills Telegram text from generated answer when missing.

### Prevention
- File-scoped user requests should always bias toward retrieval.
- Keep output-channel payload defaults late in execution so they can use generated answer context.

### Verification
- Compile checks passed for updated workflow modules.

## 2026-02-27 - Request still appears non-RAG with Telegram connection refused

### Symptom
- File-scoped query returned Telegram action only and failed with:
  - `telegram_send_message` -> `[Errno 111] Connection refused`
- User perception: RAG did not run before send action.

### Root Cause
- RAG enforcement depended on heuristic; not strict for all `file_id` cases.
- Telegram text could still fall back to generic answer, making retrieval effect invisible.
- Transport/network failure to Telegram prevented delivery regardless of retrieval outcome.

### Why This Happened
- File-linked queries should use deterministic RAG enablement, not heuristic-only.
- Output composition did not consistently expose retrieved content.

### Resolution
- Updated [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - Force `requires_rag = true` whenever `file_id` is present.
  - Build Telegram message text from `rag_context.hits` when available.
  - Fallback to generated answer only when no retrievable content exists.
- Added regression test in [tests/test_route_intent_filters.py](E:/2026/AIA/tests/test_route_intent_filters.py) for Telegram text composition from RAG hits.

### Prevention
- Treat `file_id` as hard signal for retrieval.
- Make downstream channel payload visibly grounded in retrieved context.
- Separate transport errors from retrieval quality when diagnosing failures.

### Verification
- Compile checks passed for updated node/test files.
