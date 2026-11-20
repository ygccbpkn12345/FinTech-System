# Manual Crawl Range and Analysis Date Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users choose a crawl date range and prevent unavailable analysis dates from ever entering the running UI state.

**Architecture:** Centralize backend date-range validation in a small service used before external calls. Pass the validated range into market, news and financial fetchers. Add a pure frontend guard that checks the selected analysis date before Dashboard initializes any task state.

**Tech Stack:** Python, FastAPI, pandas, Baostock, httpx, React, Ant Design, Day.js, Node test runner, pytest

---

### Task 1: Backend crawl range validation

**Files:**
- Create: `Analyst/services/crawl_date_range.py`
- Create: `Analyst/tests/test_crawl_date_range.py`

- [ ] Write failing tests for valid ranges, missing dates, invalid formats, reversed ranges and future end dates.
- [ ] Run the focused test and confirm the module is missing.
- [ ] Implement `validate_crawl_date_range(start_date, end_date, today=None)` returning ISO dates.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Apply range to Eastmoney data

**Files:**
- Modify: `Analyst/services/eastmoney_data_service.py`
- Modify: `Analyst/tests/test_eastmoney_data_service.py`

- [ ] Add failing tests showing news outside the range is discarded and financial rows announced after the end date are discarded.
- [ ] Run focused tests and verify expected failures.
- [ ] Pass start/end dates into `fetch_news`, `fetch_statement` and `fetch_all`; filter before atomic persistence.
- [ ] Run focused tests and confirm they pass.

### Task 3: Apply range to market API orchestration

**Files:**
- Modify: `Analyst/api_server.py`
- Modify: `Analyst/services/data_fetch_service.py`
- Modify: `Analyst/tests/test_data_fetch_service.py`

- [ ] Add failing tests that the result echoes the requested range.
- [ ] Run focused tests and verify failure.
- [ ] Validate request dates before login/network access, pass them to Baostock/Tushare and Eastmoney, and include them in the response.
- [ ] Run focused tests and confirm they pass.

### Task 4: Add manual date range controls

**Files:**
- Modify: `frontend/src/pages/Settings.jsx`
- Modify: `frontend/src/utils/crawlSync.js`
- Modify: `frontend/src/utils/crawlSync.test.js`

- [ ] Add failing tests for constructing a fetch request with ISO start/end dates and rejecting invalid ranges.
- [ ] Run `npm.cmd run test:crawl` and verify failure.
- [ ] Add the pure request builder and two required DatePicker controls, defaulting to one year ago through today.
- [ ] Send the selected range to `/api/data/fetch` and retain the existing status refresh behavior.
- [ ] Run the crawl tests and confirm they pass.

### Task 5: Block unavailable analysis dates before running state

**Files:**
- Create: `frontend/src/utils/analysisDateGuard.js`
- Create: `frontend/src/utils/analysisDateGuard.test.js`
- Modify: `frontend/src/pages/Dashboard.jsx`
- Modify: `frontend/src/api/configApi.js`
- Modify: `frontend/package.json`

- [ ] Add failing tests proving unavailable dates return a warning decision and available dates permit analysis.
- [ ] Run the focused Node test and verify the missing module failure.
- [ ] Add an API method for `/api/symbols/{symbol}/available-dates` and the pure guard.
- [ ] Invoke the date check before `setLoading`, `setHasStarted`, task creation or stream initialization; warn and return on failure.
- [ ] Run the focused tests and confirm they pass.

### Task 6: Documentation and complete verification

**Files:**
- Modify: `README.md`
- Modify: `Dockerfile`

- [ ] Document date-range rules and unavailable-date alert behavior.
- [ ] Add the new backend module to Docker compile checks.
- [ ] Run all backend tests and Python compile checks.
- [ ] Run all frontend tests and the production build.

Git commit steps are omitted because this workspace is not a Git repository.
