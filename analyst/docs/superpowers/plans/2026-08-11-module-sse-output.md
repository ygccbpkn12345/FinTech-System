# Module SSE Immediate Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream each saved analysis module to the browser immediately and render it in a stable module grid before the full analysis finishes.

**Architecture:** Each in-memory analysis task owns an event history and `threading.Condition`. Module and terminal state transitions append sanitized monotonic events and wake SSE subscribers; the frontend consumes them through a small `EventSource` adapter while retaining polling as the authoritative completion fallback.

**Tech Stack:** Python 3.12, FastAPI `StreamingResponse`, threading, pytest, browser `EventSource`, React 19, Node test runner, Vite, Nginx.

---

### Task 1: Add a task event stream primitive

**Files:**
- Create: `Analyst/services/task_event_stream.py`
- Create: `Analyst/tests/test_task_event_stream.py`

- [x] Write tests for ordered append, replay after `Last-Event-ID`, waiter notification, heartbeat timeout, terminal closure, and recursive secret removal.
- [x] Run `python -m pytest tests/test_task_event_stream.py -v`; expect import failure.
- [x] Implement `TaskEventStream` with a shared `threading.Condition`, monotonic IDs, immutable public event copies, `wait_after(last_id, timeout)`, and terminal detection.
- [x] Implement SSE encoding as `id`, `event`, and compact JSON `data` lines; encode heartbeats as comments without IDs.
- [x] Run `python -m pytest tests/test_task_event_stream.py -v`; expect all tests to pass.

### Task 2: Expose the FastAPI SSE endpoint

**Files:**
- Modify: `Analyst/api_server.py`
- Modify: `Analyst/tests/test_config_api.py`

- [x] Add failing API tests for initial replay, `Last-Event-ID`, terminal close, unknown-task 404, cache-control headers, and absence of credentials.
- [x] Add one `TaskEventStream` to every task at creation while excluding it from `_get_task` responses.
- [x] Route module completion through one atomic task update that appends `module_completed`, updates `modules`, and wakes subscribers.
- [x] Append `completed` or `failed` in the same critical transition that changes task status.
- [x] Add `GET /api/analyze/events/{task_id}` returning `StreamingResponse(media_type="text/event-stream")`, replaying missed events and emitting a 15-second comment heartbeat while running.
- [x] Run `python -m pytest tests/test_config_api.py tests/test_task_event_stream.py -v`; expect all tests to pass.

### Task 3: Add a tested frontend EventSource adapter

**Files:**
- Create: `frontend/src/api/analysisEvents.js`
- Create: `frontend/src/api/analysisEvents.test.js`
- Modify: `frontend/package.json`

- [x] Write Node tests with an injected fake EventSource proving normalized parsing, increasing-ID deduplication, connection-error callbacks, terminal close, and explicit cleanup.
- [x] Run `npm.cmd run test:events`; expect failure because the adapter does not exist.
- [x] Implement `subscribeAnalysisEvents(taskId, handlers, options)` using native `EventSource`, a URL derived from the configured API base, per-subscription last-ID deduplication, and a returned close function.
- [x] Run `npm.cmd run test:events`; expect all tests to pass.

### Task 4: Render stable live module slots

**Files:**
- Create: `frontend/src/components/AnalysisModuleStream.jsx`
- Modify: `frontend/src/components/AnalysisLoadingPanels.jsx`
- Modify: `frontend/src/pages/Dashboard.jsx`

- [x] Define a fixed module registry for five analysts followed by router, manager, risk, final, environment simulation, reflection, and optional weekly reflection.
- [x] Render every slot in registry order with `pending`, `running`, `completed`, or `failed` state and public payload text without reordering by arrival.
- [x] Start SSE immediately after `/api/analyze/start`, apply `module_completed` events idempotently, retain completed cards during reconnect, and show a reconnecting notice for network errors.
- [x] On `completed`, close SSE and fetch the authoritative full result; on `failed`, close SSE and surface the safe error. Close old streams on cancellation, new task, and unmount.
- [x] Retain status polling for progress and fallback completion, but do not clear live module state between reconnect attempts.
- [x] Run `npm.cmd run test:events` and `npm.cmd run build`; expect both to pass.

### Task 5: Configure the reverse proxy for streaming

**Files:**
- Modify: `docker/nginx.conf`

- [x] Add a more-specific `/api/analyze/events/` location before `/api/` with HTTP/1.1 proxying, `proxy_buffering off`, `proxy_cache off`, `gzip off`, an empty `Connection` header, and a 600-second read timeout.
- [x] Run `rg -n "analyze/events|proxy_buffering off|proxy_cache off|gzip off" docker/nginx.conf`; expect all directives.

### Task 6: Full verification

**Files:**
- Verify all modified files.

- [x] Run from `Analyst`: `python -m pytest tests -v`; expect zero failures.
- [x] Run from `Analyst`: `python -m compileall api_server.py services`; expect exit code 0.
- [x] Run from `frontend`: `npm.cmd run test:events`; expect zero failures.
- [x] Run from `frontend`: `npm.cmd run build`; expect exit code 0.
- [x] Run targeted ESLint on new and modified frontend files; record existing JSX-variable baseline findings separately.
- [x] Confirm the workspace has no Git repository and report files plus verification evidence without claiming commits.
