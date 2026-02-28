# Execution Strategy Report

## 1. Purpose
Define a production-safe strategy to automatically switch between parallel and sequential sub-agent execution.

## 2. Decision Inputs
- Feature flags:
  - `ACCEPT_PARALLEL` (environment default)
  - `accept_parallel` (per-request override)
- Route output:
  - `action_plans[]`
  - `depends_on` dependency constraints

## 3. Automatic Switching Algorithm
1. Build dependency graph from route actions.
2. Compute dependency layers:
   - Layer 0: actions with no dependencies.
   - Layer N: actions whose dependencies are all in earlier layers.
3. If parallel mode enabled:
   - execute actions concurrently within each layer.
   - execute layers sequentially.
4. If parallel mode disabled:
   - execute actions sequentially in route order.
5. Return `action_results` in original route plan order.

## 4. Grouping Semantics
- Parallel group:
  - actions in same layer with no unmet dependencies.
- Sequential group:
  - layer boundaries and explicit dependency chains.

## 5. Examples
- Parallel:
  - `jira_create_issue` and `telegram_send_message` with `depends_on=[]`.
- Sequential:
  - `jira_search_issues -> telegram_send_message` (summary depends on search output).
  - `jira_create_issue -> jira_assign_issue` (assign needs created issue key).

## 6. Failure Handling
- If parent action fails/skips:
  - dependent actions are marked `skipped`.
- If unresolved/cyclic dependency is detected:
  - unresolved actions are marked `skipped` with dependency error.

## 7. Observability and KPIs
- total workflow runtime
- per-step runtime
- parallel layer count per request
- success/failure/skipped ratios per action
- sequential vs parallel latency delta

## 8. Product/Delivery Notes
- PM: expected p95 latency reduction for multi-action requests.
- PDM: UI can show parallel activity and per-step timing.
- Analyst: compare performance by toggling `accept_parallel` in A/B style tests.
