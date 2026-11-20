# Algorithm Registry Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task in this session.

**Goal:** Provide persistent Python/HTTP algorithm CRUD and live chat discovery.

**Architecture:** A shared ToolRegistry supplies per-turn snapshots. AlgorithmManager validates definitions, adapts trusted local implementations or fixed-URL HTTP tools, and atomically persists changes before publishing them.

**Tech Stack:** Existing Python, FastAPI, Pydantic, httpx, React and Ant Design; no new dependencies.

**Spec:** ../specs/2026-11-02-algorithm-registry-design.md

## Global Constraints

- Preserve existing stock prediction/crawler and ToolResult wire format.
- Never import client-selected Python modules or use model arguments as a request URL.
- Keep unrelated existing working tree edits untouched; do not commit them.
- Single backend process; JSON storage survives restarts, including deletion of all tools.

## Review Focus

- Zero/false are valid required arguments; blank strings and None are missing.
- Invalid/duplicate definitions must not modify disk or registry.
- Disk failure must retain the previous live registry.
- Deleted pending tools must yield a chat error rather than HTTP 500.
- New generic tools must support multi-turn required arguments without stock-specific extraction.

### Task 1: Unified contract and persistent manager

Files: services/tools/__init__.py, services/tool_registry.py, services/algorithm_manager.py, services/tools/plugins/, tests/test_algorithm_manager.py.

- [x] Add failing tests for CRUD/reload, validation, atomic failure, zero/false, plugin discovery.
- [x] Run targeted pytest and confirm missing implementation fails.
- [x] Add Tool protocol, shared missing-parameter helper, managed adapters, registry snapshot/register/update/remove/replace, atomic JSON store and trusted plugin discovery.
- [x] Run manager/registry/HTTP tests.

### Task 2: API and dynamic chat

Files: services/algorithm_api.py, api_server.py, services/chat_router.py, services/chat_orchestrator.py, services/tools/http_tool.py, tests/test_algorithm_api.py, tests/test_algorithm_chat.py.

- [x] Add failing tests for CRUD status codes, dynamic discovery/deletion and generic continuation.
- [x] Register shared manager/router; use a coherent registry snapshot each chat turn; support model-assisted arguments plus single-parameter text and key=value fallback.
- [x] Correct GET transport and centralize required checks.
- [x] Run backend tests with external model/network disabled in new tests.

### Task 3: Algorithm management page and documentation

Files: frontend/src/pages/Algorithms.jsx, frontend/src/api/algorithmApi.js, frontend/src/App.jsx, frontend/src/components/AppLayout.jsx, frontend/src/components/chat/ChatSidebar.jsx, docs/algorithm-registry.md.

- [x] Add table/search/type filter, add/edit form with local selector or fixed HTTP settings, delete confirmation and failure feedback.
- [x] Add navigation, document local plugin and HTTP registration examples.
- [x] Run frontend tests and production build, inspect final diff and backend suite.

## Verification and review

- Backend: `.venv/Scripts/python.exe -m pytest --ignore=test_baostock.py -q` → 166 passed. `test_baostock.py` is a manual live network script that logs into baostock at import time, with no unit tests; excluded from offline verification.
- Existing task-start/conversation tests now explicitly inject available validation instead of depending on the mutable 2024-01-03 market CSV. Production validation and market files are unchanged.
- Frontend: all files found by `rg --files frontend/src -g '*.test.js'`, executed with `node --test` → 50 passed. `npm run build` → success, existing bundle size warning remains.
- New page/API ESLint checks pass with `no-unused-vars.varsIgnorePattern=^[A-Z]` to account for JSX component imports. The repository config otherwise incorrectly marks JSX imports as unused, including existing pages; repository-wide lint config is unchanged.
- Independent reviewer found generic continuation incorrectly skipped stock-named parameters. Fixed with three RED→GREEN regressions for AAPL, JSON and key=value, followed by the passing backend suite.
- Browser check: create temporary HTTP algorithm, edit description, delete it, verify built-in Python edit fields; temporary test entry removed. Fixed initial modal field values with connected, force-rendered Form.
- Persistence restart verified against the running local backend. Runtime storage is configurable with ALGORITHM_REGISTRY_PATH; Docker uses its existing runtime directory.
- No commits or changes to unrelated user data/configuration.
