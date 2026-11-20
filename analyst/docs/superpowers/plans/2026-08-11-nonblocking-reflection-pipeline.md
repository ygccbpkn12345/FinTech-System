# Nonblocking Reflection Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete analysis immediately after the final decision while historical reflection continues in a bounded background worker and today's analysis skips postprocessing.

**Architecture:** Split the runner's serial node registry at `final_decision`, return and publish the mapped main result first, then run environment/reflection/weekly nodes from a copied state. Track postprocessing independently on the in-memory task record and merge only reflection/environment fields into the published result. The dashboard removes postprocessing UI, while the reflection page renders explicit lifecycle states.

**Tech Stack:** Python 3, FastAPI, concurrent.futures, pytest, React 19, Ant Design, Node test runner, Vite.

---

### Task 1: Split main analysis from reflection postprocessing

**Files:**
- Modify: `Analyst/graph/graph_workflow.py`
- Modify: `Analyst/graph/train.py`
- Test: `Analyst/tests/test_pipeline_coordinator.py`

- [ ] Add a failing test proving the main run stops after `final_decision` and postprocessing can resume from a copied snapshot.
- [ ] Run `python -m pytest tests/test_pipeline_coordinator.py -q` from `Analyst`; expect the new test to fail.
- [ ] Expose separate main and postprocessing registries and runner methods, preserving the existing `run()` compatibility method.
- [ ] Re-run the focused test; expect all tests to pass.

### Task 2: Publish the main result before bounded background reflection

**Files:**
- Modify: `Analyst/services/analysis_runner.py`
- Modify: `Analyst/services/pipeline_service.py`
- Modify: `Analyst/api_server.py`
- Create: `Analyst/tests/test_nonblocking_reflection_pipeline.py`

- [ ] Add failing tests for historical submission, today's `not_applicable`, immediate main completion, background failure isolation, and reflection-only merge.
- [ ] Run `python -m pytest tests/test_nonblocking_reflection_pipeline.py -q`; expect failures for missing lifecycle behavior.
- [ ] Add a bounded module-level executor, server-local date comparison, independent `postprocessing` state, and a background callback that updates only environment/reflection fields.
- [ ] Make main result mapping tolerate absent reflection fields and complete SSE at `final_decision`.
- [ ] Re-run focused backend tests; expect all to pass.

### Task 3: Remove reflection from the dashboard flow

**Files:**
- Modify: `frontend/src/components/AnalysisWorkbenchTabs.jsx`
- Modify: `frontend/src/utils/processStepUtils.js`
- Modify: `frontend/src/components/AnalysisModuleStream.jsx`
- Create: `frontend/src/utils/nonblockingPipeline.test.js`

- [ ] Add failing tests proving UI step/module definitions exclude environment and reflection nodes.
- [ ] Run `node --test src/utils/nonblockingPipeline.test.js`; expect failure.
- [ ] Remove the reflection workbench tab and restrict visible step/module definitions through final decision; ignore legacy hidden module events.
- [ ] Re-run the focused test; expect it to pass.

### Task 4: Render reflection lifecycle states

**Files:**
- Modify: `Analyst/api_server.py`
- Modify: `frontend/src/api/analysisApi.js`
- Modify: `frontend/src/utils/analysisStorage.js`
- Modify: `frontend/src/pages/Reflection.jsx`
- Test: `Analyst/tests/test_nonblocking_reflection_pipeline.py`
- Modify: `frontend/src/utils/nonblockingPipeline.test.js`

- [ ] Add failing backend/API and frontend normalization tests for `pending`, `running`, `completed`, `failed`, and `not_applicable`, including stock/date identity.
- [ ] Add a task reflection-status endpoint and polling client; persist task identity with local history records.
- [ ] Render lifecycle alerts and retain a clearly identified latest completed historical reflection when today's task is not applicable.
- [ ] Run focused backend and frontend tests; expect all to pass.

### Task 5: Regression verification

**Files:**
- Verify only.

- [ ] Run `python -m pytest tests -q` from `Analyst`; expect all tests to pass.
- [ ] Run all Node test scripts and `npm run build` from `frontend`; expect all tests and the production build to pass.
- [ ] Review the design acceptance criteria against implemented tests and record any environmental limitation (no Git metadata/worktree/commits).
