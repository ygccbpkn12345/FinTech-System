# Eastmoney News and Fundamentals Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `/api/data/fetch` so Baostock market crawling also fetches Eastmoney stock news and all three financial statements, persists them in the existing analyzer format, and returns synchronized module status.

**Architecture:** Put Eastmoney HTTP and response-normalization logic in a focused service. Keep the FastAPI endpoint as an orchestration layer and preserve existing files through validated atomic writes. Return per-module results plus the existing symbol status snapshot.

**Tech Stack:** Python 3, httpx, pandas, FastAPI, pytest

---

### Task 1: Eastmoney identifiers and response normalization

**Files:**
- Create: `Analyst/services/eastmoney_data_service.py`
- Create: `Analyst/tests/test_eastmoney_data_service.py`

- [ ] Write failing tests for Shanghai/Shenzhen security identifiers, news field mapping and malformed/empty payload rejection.
- [ ] Run `python -m pytest tests/test_eastmoney_data_service.py -q` from `Analyst`; verify failures are caused by the missing service.
- [ ] Implement identifier conversion, payload extraction, news normalization and explicit response errors.
- [ ] Re-run the focused tests and verify they pass.

### Task 2: Financial-statement normalization

**Files:**
- Modify: `Analyst/services/eastmoney_data_service.py`
- Modify: `Analyst/tests/test_eastmoney_data_service.py`

- [ ] Add failing tests for balance, income and cash-flow payload conversion, report-date ordering and duplicate replacement by the newest update date.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Implement a shared financial payload normalizer that preserves all returned columns and validates the report-date column.
- [ ] Re-run the focused tests and verify they pass.

### Task 3: Pagination, retry and safe persistence

**Files:**
- Modify: `Analyst/services/eastmoney_data_service.py`
- Modify: `Analyst/tests/test_eastmoney_data_service.py`

- [ ] Add failing tests using an injected HTTP transport for multi-page news, independent statement failures, merging old news, and atomic target replacement.
- [ ] Run the tests and confirm the requested client behavior is absent.
- [ ] Implement bounded pagination/retries, four independent fetch operations and validated temporary-file replacement.
- [ ] Re-run the focused tests and verify they pass.

### Task 4: Fetch endpoint orchestration and status contract

**Files:**
- Modify: `Analyst/api_server.py`
- Create: `Analyst/services/data_fetch_service.py`
- Create: `Analyst/tests/test_data_fetch_service.py`

- [ ] Add failing service tests proving full success returns `ok`, a single Eastmoney failure returns `partial`, and all results include refreshed `dataStatus`.
- [ ] Run the focused tests and verify the expected failures.
- [ ] Extract the existing market-fetch/save flow into the coordinator and call the Eastmoney service after market success.
- [ ] Return `modules`, `failedModules`, counts, latest market date and refreshed symbol status; keep `error` for market failure.
- [ ] Re-run the focused tests and verify they pass.

### Task 5: Frontend partial-result handling

**Files:**
- Modify: `frontend/src/pages/Settings.jsx`
- Modify: `frontend/src/utils/crawlSync.js`
- Modify: `frontend/src/utils/crawlSync.test.js`

- [ ] Add a failing Node test proving `partial` results still refresh the selected stock and expose failed module names.
- [ ] Run `npm.cmd run test:crawl` and verify the expected failure.
- [ ] Implement partial-result normalization and show a warning while refreshing data status and the smart-analysis state.
- [ ] Re-run the frontend crawl test and verify it passes.

### Task 6: Documentation and verification

**Files:**
- Modify: `README.md`
- Modify: `Dockerfile` only if verification reveals a missing runtime dependency.

- [ ] Document that crawler mode uses Baostock for market data and Eastmoney for news/financial statements, including `partial` semantics.
- [ ] Run `python -m pytest tests -q` from `Analyst` and require zero failures.
- [ ] Run frontend test scripts and `npm.cmd run build`; require zero failures.
- [ ] Check the implementation against every requirement in the approved design and report any external-interface limitation explicitly.

Git commit steps are omitted because `D:\code\服务大赛` is not a Git repository.
