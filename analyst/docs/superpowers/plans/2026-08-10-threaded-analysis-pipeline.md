# Threaded Analysis Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run five analyst LLM nodes concurrently, then execute the decision chain serially, while a fixed three-thread I/O pool persists module snapshots and events asynchronously.

**Architecture:** Introduce a focused pipeline coordinator that owns explicit fan-out/fan-in and deterministic state merging instead of relying on LangGraph `Send`. A bounded I/O dispatcher writes atomic task-scoped module artifacts and accumulates failures. Existing node factories remain the business-logic boundary and the analysis runner calls the coordinator.

**Tech Stack:** Python 3.12, `concurrent.futures`, threading, LangGraph node factories, pytest, FastAPI, React/Vite.

---

### Task 1: Specify coordinator concurrency and merge behavior

**Files:**
- Create: `Analyst/tests/test_pipeline_coordinator.py`
- Create: `Analyst/services/pipeline_coordinator.py`

- [ ] Write failing tests using five controlled analyst callables and serial decision callables. Record thread IDs, start/end barriers and call order; assert five analysts overlap, router starts after every analyst ends, and all serial nodes run on the caller thread in fixed order.
- [ ] Run `python -m pytest tests/test_pipeline_coordinator.py -v`; expect failures because `AnalysisPipelineCoordinator` does not exist.
- [ ] Implement `AnalysisPipelineCoordinator` with `ThreadPoolExecutor(max_workers=5, thread_name_prefix="analyst")`, deterministic analyst-name order and a direct caller-thread serial loop.
- [ ] Add a failing test where two analysts return the same owned field; expect `PipelineStateConflictError` naming both modules and the field.
- [ ] Implement explicit analyst field ownership and deterministic state-delta merging without completion-order overwrites.
- [ ] Run `python -m pytest tests/test_pipeline_coordinator.py -v`; expect all coordinator tests to pass.

### Task 2: Implement bounded three-thread I/O dispatch

**Files:**
- Create: `Analyst/tests/test_module_io_dispatcher.py`
- Create: `Analyst/services/module_io_dispatcher.py`

- [ ] Write failing tests asserting I/O overlaps later model work, uses no more than three worker thread IDs, atomically creates task-scoped module JSON, assigns increasing event sequence values and waits for all work during `close()`.
- [ ] Run `python -m pytest tests/test_module_io_dispatcher.py -v`; expect import failure.
- [ ] Implement `ModuleSnapshot` as an immutable dataclass and `ModuleIODispatcher` with three workers plus a 12-slot semaphore guarding submitted-but-unfinished work.
- [ ] Implement task directory validation, temporary sibling write, `flush`/`fsync`, `os.replace`, event locking and secret-field exclusion.
- [ ] Add a failing test for an injected write exception; assert `ModuleIOError` is raised by `close()` with the module name after other submitted work is drained.
- [ ] Implement future tracking and aggregated close-time errors, then rerun the I/O tests to green.

### Task 3: Wire existing model nodes into the coordinator

**Files:**
- Modify: `Analyst/graph/graph_workflow.py`
- Modify: `Analyst/graph/train.py`
- Modify: `Analyst/graph/node_utils.py`
- Modify: `Analyst/services/analysis_runner.py`
- Test: `Analyst/tests/test_pipeline_coordinator.py`

- [ ] Add failing integration tests with fake LLM-backed node factories proving the real workflow exposes five analyst callables and the ordered serial chain without `Send` fan-out.
- [ ] Refactor `TextGradTraderWorkflow` to build a node registry with analyst ownership metadata and ordered serial node names. Remove `fan_out_analysts`, `Send`, analyst semaphore setup and `limit_analyst_concurrency` behavior.
- [ ] Change `TextGradTraderRunner.run` to create the coordinator and dispatcher, run from the initialized state, and always close both executors in `finally`.
- [ ] After each node result, submit an immutable public module snapshot; keep final state mapping unchanged.
- [ ] Pass task ID and a task-scoped module-output root from `api_server` through `pipeline_service` and `analysis_runner` into the runner.
- [ ] Run coordinator, configuration and API tests; expect all to pass.

### Task 4: Propagate module status and failures to task state

**Files:**
- Modify: `Analyst/api_server.py`
- Modify: `Analyst/services/pipeline_service.py`
- Test: `Analyst/tests/test_config_api.py`

- [ ] Add failing API tests asserting each task contains `modules` and `events`, module completion updates occur independently, and an I/O close failure produces task status `failed` with a safe module-specific message.
- [ ] Add thread-safe `on_module_event` handling that appends ordered public events and updates per-module state under `_tasks_lock`.
- [ ] Pass callbacks through the service stack to the dispatcher; do not expose configuration snapshots or credentials.
- [ ] Run `python -m pytest tests/test_config_api.py tests/test_pipeline_coordinator.py tests/test_module_io_dispatcher.py -v`; expect all tests to pass.

### Task 5: Remove obsolete analyst concurrency configuration

**Files:**
- Modify: `Analyst/config.py`
- Modify: `Analyst/services/runtime_config.py`
- Modify: `Analyst/api_server.py`
- Modify: `frontend/src/pages/Settings.jsx`
- Modify: `frontend/src/utils/systemConfig.js`
- Modify: `README.md`
- Test: `Analyst/tests/test_runtime_config.py`

- [ ] Add a failing test asserting `analystConcurrency` is absent from public runtime configuration and ignored when supplied by an old client.
- [ ] Remove `llm_analyst_concurrency` defaults, persistence, request models, runtime view and runner semaphore calls while continuing to read old JSON files without failure.
- [ ] Remove the UI field and request normalization; document fixed five analyst workers and three I/O workers.
- [ ] Run backend tests and `npm.cmd run build`; expect both to pass.

### Task 6: Full verification

**Files:**
- Verify all modified files.

- [ ] Run from `Analyst`: `python -m pytest tests -v`; expect zero failures.
- [ ] Run from `Analyst`: `python -m compileall config.py api_server.py graph services`; expect exit code 0.
- [ ] Run from `frontend`: `npm.cmd run build`; expect exit code 0.
- [ ] Run targeted ESLint on modified frontend files with `npx.cmd eslint src/pages/Settings.jsx src/utils/systemConfig.js`; record existing baseline findings separately from new failures.
- [ ] Inspect a temporary module-output directory and assert task scoping, event ordering, valid JSON and absence of test credentials.
- [ ] Since this workspace has no Git repository, report changed files and verification evidence without claiming commits or branch integration.
