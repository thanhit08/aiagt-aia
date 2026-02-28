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

## 2026-02-28 - Telegram `chat not found` after workflow refactor

### Symptom
- Action execution failed with:
  - `telegram:telegram_send_message failed: http_400: Bad Request: chat not found ...`
- User reported this flow worked before recent workflow/enrichment updates.

### Root Cause
- `chat_id` was being sourced from planner/LLM-generated action params in the route/enrichment pipeline.
- That generated value could override the known-good default from `TELEGRAM_DEFAULT_CHAT_ID`.

### Why This Happened
- The previous protection only removed model-injected `chat_id` in one branch.
- Route-produced params could still carry `chat_id`, and were treated as trusted.

### Resolution
- Hardened Telegram param sanitization in [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - treat `chat_id` as protected routing data
  - drop planner/LLM `chat_id` by default
  - allow explicit override only from trusted API input `telegram_chat_id`
- Added optional `telegram_chat_id` in [src/aia/api/main.py](E:/2026/AIA/src/aia/api/main.py) and state wiring in [src/aia/workflow/state.py](E:/2026/AIA/src/aia/workflow/state.py).
- Added regression tests in [tests/test_telegram_chat_id_sanitization.py](E:/2026/AIA/tests/test_telegram_chat_id_sanitization.py).

### Prevention
- Keep transport routing identifiers (`chat_id`) out of planner authority.
- Only accept channel routing overrides from explicit user/API fields.

### Verification
- Unit tests cover both:
  - default path ignores model/planner `chat_id`
  - trusted request override sets `chat_id`

## 2026-02-28 - Stale failed response returned from Redis cache

### Symptom
- User retried same request after fix but still received old failed payload.

### Root Cause
- `/qa-intake` cached all responses, including failed action executions.
- Cache key is deterministic by `user_id + instruction + file_id`, so retries could return stale failures.

### Why This Happened
- Cache layer optimized latency but did not distinguish successful vs failed outcomes.

### Resolution
- Updated [src/aia/api/main.py](E:/2026/AIA/src/aia/api/main.py):
  - only cache responses when `errors` is empty and no action has `status=failed`.

### Prevention
- Cache only stable successful outputs, or include failure-aware invalidation policy.

## 2026-02-27 - Jira still appears in action plan for file-to-Telegram intent

### Symptom
- For request "Get all issues in the file related to accuracy and send to Telegram channel", `action_plans` still contained:
  - Jira `jira_search_issues`
  - Telegram `telegram_send_message`

### Root Cause
- Intent filter `_is_file_delivery_without_explicit_jira` required `file_id` to be present.
- When `file_id` was absent or not propagated in a given run, Jira pruning policy did not activate.

### Why This Happened
- Policy mixed semantic intent check with transport payload availability.
- User intent ("in the file" + "send to Telegram") should drive routing constraints regardless of missing `file_id`.

### Resolution
- Updated intent filter in [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - remove hard dependency on `file_id`
  - trigger Jira pruning from instruction intent only:
    - file-scoped phrase present
    - Telegram requested
    - Jira not explicitly requested
- Added regression test in [tests/test_route_intent_filters.py](E:/2026/AIA/tests/test_route_intent_filters.py) for no-`file_id` scenario.

### Prevention
- Use user intent as source of truth for routing constraints.
- Keep payload availability checks separate from intent policies.

### Verification
- Compile checks passed for updated node/test files.

## 2026-02-27 - Jira create/assign chain failed in mixed file->Telegram->Jira flow

### Symptom
- `jira_create_issue` failed with:
  - `project: Could not find project by id or key`
- `jira_assign_issue` failed with:
  - missing `issue_key`

### Root Cause
- Planner emitted `jira_create_issue` with empty params (`{}`), missing required Jira `fields.project` and ticket content.
- Planner emitted `jira_assign_issue` without guaranteed `issue_key` and assign preconditions.
- Runtime execution did not enforce dependency success before executing dependent actions.

### Why This Happened
- Parameter preparation for Jira actions was not deterministic.
- Dependency semantics in `depends_on` were not enforced in executor.

### Resolution
- Updated [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - Add dependency-aware execution: actions are skipped when dependency fails.
  - Add Jira create param builder:
    - derive `fields.summary` + `fields.description` from request/RAG context
    - require project key via `JIRA_DEFAULT_PROJECT_KEY` (or existing `fields.project`)
    - default issue type from `JIRA_DEFAULT_ISSUE_TYPE` (default `Bug`)
  - Add Jira assign param prep:
    - derive `issue_key` from successful `jira_create_issue`
    - require `accountId` or `JIRA_DEFAULT_ASSIGNEE_ACCOUNT_ID`
  - Add clearer deterministic validation errors instead of raw exceptions.
- Tightened mixed-intent action policy:
  - drop unneeded `jira_search_issues` and `jira_assign_issue` unless explicitly requested.

### Prevention
- Enforce pre-execution parameter validation for write actions.
- Enforce dependency success before running dependent actions.
- Do not execute planner-generated optional actions unless explicitly requested by intent.

### Verification
- Local compile checks passed for updated workflow modules.

## 2026-02-28 - Answer step output contradicted user intent (unrequested Jira tickets)

### Symptom
- Request: "Get all issues in the file related to accuracy and send to Telegram channel."
- Answer node output included: "create Jira ticket(s) according to your request."
- This contradicted the original request and confused downstream behavior.

### Root Cause
- Answer fallback normalization used a hardcoded recovery sentence that always mentioned Jira tickets in some branches.
- Post-processing did not validate answer text against requested systems/actions.

### Why This Happened
- Defensive answer fallback was implemented for missing-input prompts, but it was not intent-aware.
- No guard removed unrequested Jira commitments from final answer text.

### Resolution
- Added intent-aware answer normalization in [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - `_normalize_answer_to_intent(answer, state)`
  - strips Jira/ticket commitments when user did not request Jira
  - preserves Jira references when Jira is explicitly requested
  - provides file+telegram grounded fallback text for missing-input prompt cases
- Added targeted regression tests in [tests/test_answer_normalization.py](E:/2026/AIA/tests/test_answer_normalization.py).

### Prevention
- Always run answer output through intent-consistency checks before returning.
- Keep fallback templates dynamic to requested channels/tools, never hardcoded to one system.

### Verification
- Compile checks passed for updated modules and tests.

## 2026-02-27 - Jira create issue failed with error `'data'`

### Symptom
- Action result:
  - `system: jira`
  - `action: jira_create_issue`
  - `status: failed`
  - `error: 'data'`

### Root Cause
- `jira_create_issue` handler assumed `_jira_response(...)` always returned a successful payload with `data` object.
- On Jira API failure, `_jira_response` returns `{"status":"failed","error":...}` without `data`.
- Code accessed `data["data"]` directly and raised `KeyError: 'data'`.

### Why This Happened
- Post-processing logic (extracting issue key and building browse URL) did not guard failed response shape.

### Resolution
- Updated [src/aia/services/real_clients.py](E:/2026/AIA/src/aia/services/real_clients.py):
  - if create response is not success, return failure result directly.
  - guard payload type before accessing issue key.
  - only append `url` when `key` exists in successful response.

### Prevention
- Never assume success payload shape after external API calls.
- Keep post-processing conditional on `status == success`.

### Verification
- Local compile checks passed for updated client module.

## 2026-02-27 - File-scoped "add ticket to Jira" request still includes `jira_search_issues`

### Symptom
- Request: "Get all issues in the file related to accuracy and send to Telegram channel and add ticket to Jira"
- Route/action plans included:
  - `jira_search_issues`
  - `telegram_send_message`
  - `jira_create_issue`
- Expected: no Jira search unless explicitly requested.

### Root Cause
- Planner produced extra Jira search action.
- Post-planning policy did not prune unneeded Jira search for file-scoped create-ticket intents.
- Dependencies still referenced removed/irrelevant actions.

### Why This Happened
- Existing policy covered "file -> telegram without Jira", but not "file -> telegram + Jira create".
- Search action fallback remained in mixed-intent plan.

### Resolution
- Updated [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py):
  - detect file-scoped Jira create intent
  - remove `jira_search_issues` unless user explicitly asks Jira search/list/find
  - reconcile `depends_on` to remove references to pruned actions
- Added regression test in [tests/test_route_intent_filters.py](E:/2026/AIA/tests/test_route_intent_filters.py).

### Prevention
- Apply deterministic policy checks after LLM planning for mixed-intent requests.
- Always clean dependencies after action pruning.

### Verification
- Compile checks passed for updated node/test files.
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

## 2026-02-27 - UI workflow stuck at intake then jumps to done

### Symptom
- Streamlit workflow visualization stayed on `intake` for most of request duration.
- At completion, UI jumped directly to `done` with missing intermediate node updates.

### Root Cause
- Status updates relied on graph streaming behavior, which did not consistently emit per-node events in this runtime path.

### Why This Happened
- `graph.stream(..., stream_mode="updates")` event granularity depended on backend graph execution mode and wrappers.
- UI polling was correct but backend status source was too coarse.

### Resolution
- Replaced status source with deterministic per-node execution path in [src/aia/api/main.py](E:/2026/AIA/src/aia/api/main.py).
- API now executes workflow nodes sequentially for `/qa-intake` status tracking and writes status before each node.

### Prevention
- For UX-critical progress bars, use explicit state transitions controlled by application code.
- Keep graph-level streaming as optional optimization, not sole progress source.

### Verification
- Local compile check passed for API/Streamlit.

## 2026-02-27 - Route emitted non-catalog action `telegram_send_to_telegram`

### Symptom
- Execution failed with `Unsupported Telegram action: telegram_send_to_telegram`.

### Root Cause
- LLM generated non-canonical action name outside executor-supported fixed action set.

### Why This Happened
- Prompts requested valid actions conceptually but did not enforce explicit allow-list strongly enough.
- Normalization layer did not include this alias initially.

### Resolution
- Enforced fixed action catalog normalization in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py):
  - add alias `telegram_send_to_telegram` -> `telegram_send_message`
  - force unknown actions to safe catalog defaults per system.
- Strengthened prompt constraints in:
  - [specs/v1/prompts/enrichment.system.md](E:/2026/AIA/specs/v1/prompts/enrichment.system.md)
  - [specs/v1/prompts/orchestrator-routing.system.md](E:/2026/AIA/specs/v1/prompts/orchestrator-routing.system.md)
- Added regression test in [tests/test_enrichment_normalization.py](E:/2026/AIA/tests/test_enrichment_normalization.py).

### Prevention
- Keep explicit allow-list in both prompt and runtime normalization.
- Never execute action names not in fixed catalog.

### Verification
- Compile checks passed and regression test added.

## 2026-02-27 - File request intent contaminated by conversation history (Jira-biased enrichment)

### Symptom
- User asked file-scoped request: "Get all issues in the file related to accuracy and send to Telegram"
- Enrichment/answer drifted toward Jira-assignee flow ("issues assigned to you in Jira").

### Root Cause
- Enrichment prompt consumed merged instruction containing prior conversation summary/history.
- Older Jira-oriented context influenced current intent extraction.
- Action normalization had a Jira-biased fallback for unknown/missing system/action combinations.

### Why This Happened
- Current request and history context were not separated for intent classification.
- Unknown action/system fallback overfit to Jira default behavior.

### Resolution
- Added `raw_instruction` to workflow state and pass original user request from API.
- Updated enrichment and retrieval query defaults in [src/aia/workflow/nodes.py](E:/2026/AIA/src/aia/workflow/nodes.py) to use current request text, not merged history.
- Kept conversation context available for answer generation but separated from primary instruction field.
- Removed Jira-biased fallback path in [src/aia/workflow/enrichment.py](E:/2026/AIA/src/aia/workflow/enrichment.py):
  - fallback system is now `unknown`
  - canonical prefixed actions (`telegram_*`, `jira_*`, `slack_*`) infer system directly
  - unknown values no longer implicitly map to Jira by default.
- Added regression coverage in [tests/test_enrichment_normalization.py](E:/2026/AIA/tests/test_enrichment_normalization.py).

### Prevention
- Always separate "current user request" from "conversation memory" at intent-extraction boundary.
- Avoid provider-biased defaults for unknown action/system values.

### Verification
- Local compile checks passed for updated modules.
