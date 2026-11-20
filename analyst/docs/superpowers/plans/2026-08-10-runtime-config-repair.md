# Runtime Configuration Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make system configuration save reliably, survive refresh and restart, apply to the next analysis immediately, and persist API credentials encrypted with `CONFIG_ENCRYPTION_KEY`.

**Architecture:** Replace the split JSON/`.env` mutation paths with one locked runtime configuration repository. Store non-sensitive values directly and sensitive values as Fernet ciphertext derived from the server-provided string; give each analysis an immutable effective configuration snapshot. Keep the existing API routes compatible while making the frontend consume the server response as the source of truth.

**Tech Stack:** Python 3.12, FastAPI/Pydantic, `cryptography.fernet`, pytest, React 19, Ant Design, Vite.

---

## File structure

- Create `Analyst/tests/test_runtime_config.py`: repository, encryption, merge priority and concurrency regression tests.
- Create `Analyst/tests/test_config_api.py`: FastAPI configuration route and analysis snapshot tests.
- Modify `Analyst/services/runtime_config.py`: the sole runtime configuration repository and encryption boundary.
- Modify `Analyst/config.py`: effective snapshot construction without duplicate merge rules.
- Modify `Analyst/api_server.py`: unified request models/routes and explicit configuration errors.
- Modify `Analyst/services/analysis_runner.py`: consume one immutable effective snapshot.
- Modify `Analyst/requirements.txt` and `Analyst/pyproject.toml`: add runtime/test dependencies.
- Modify `frontend/src/api/configApi.js`: unified model/data-source configuration calls.
- Modify `frontend/src/utils/systemConfig.js`: normalize credential status and stop attaching cached settings to analysis requests.
- Modify `frontend/src/pages/Settings.jsx`: load/save verified server state and explicit credential clearing.
- Modify `README.md`: document `CONFIG_ENCRYPTION_KEY` and runtime behavior.

### Task 1: Lock down configuration behavior with backend tests

**Files:**
- Create: `Analyst/tests/test_runtime_config.py`
- Modify: `Analyst/requirements.txt`
- Modify: `Analyst/pyproject.toml`

- [ ] **Step 1: Add test dependencies**

Add `cryptography>=43,<46`, `pytest>=8,<9`, and `httpx>=0.27,<1` to both dependency manifests.

- [ ] **Step 2: Write failing repository tests**

Create fixtures that monkeypatch `RUNTIME_CONFIG_PATH` to `tmp_path / "runtime.json"` and set `CONFIG_ENCRYPTION_KEY="competition-secret"`. Test these concrete cases: update and reload non-sensitive values; persisted JSON contains neither `sk-secret-value` nor `tushare-secret-value`; a module reload decrypts both credentials; blank credential input preserves ciphertext; `clearApiKey=True` removes only the API key; missing/wrong master key raises `RuntimeConfigEncryptionError`; 20 concurrent updates leave parseable JSON.

- [ ] **Step 3: Run tests and verify failure**

Run: `python -m pytest tests/test_runtime_config.py -v`

Expected: FAIL because encrypted credentials, explicit clearing, and the repository error type do not exist.

- [ ] **Step 4: Commit checkpoint if Git is available**

Run: `git add Analyst/tests/test_runtime_config.py Analyst/requirements.txt Analyst/pyproject.toml && git commit -m "test: define runtime config guarantees"`

Expected in this workspace: skip with a note because the directory is not a Git repository.

### Task 2: Implement the unified encrypted repository

**Files:**
- Modify: `Analyst/services/runtime_config.py`
- Modify: `Analyst/config.py`
- Test: `Analyst/tests/test_runtime_config.py`

- [ ] **Step 1: Add explicit repository errors and schema constants**

Define `RuntimeConfigError`, `RuntimeConfigValidationError`, and `RuntimeConfigEncryptionError`. Extend persisted keys with `data_source` and `crawl_url`; define sensitive mappings for `api_key` and `tushare_token` plus `clearApiKey`/`clearTushareToken` flags.

- [ ] **Step 2: Implement string-to-Fernet key derivation**

Use `hashlib.pbkdf2_hmac("sha256", master.encode(), salt, 390_000, dklen=32)` and URL-safe base64 encoding. Persist a random 16-byte salt as base64 under `_encryption.salt`; encrypt credentials under `_secrets.<field>` and never persist the master string.

- [ ] **Step 3: Implement atomic locked persistence**

Under the existing `RLock`, serialize to a temporary sibling file, flush and `os.fsync`, then call `os.replace(temp_path, RUNTIME_CONFIG_PATH)`. On failure, remove only that exact temporary file and preserve the old configuration.

- [ ] **Step 4: Implement normalized read/update/snapshot methods**

Make `get_runtime_config()` return camelCase public values and credential status only. Make `get_runtime_config_internal()` decrypt secrets and return snake_case internal values. Make `update_runtime_config()` validate positive timeout/retry/concurrency values and supported data sources, preserve omitted credentials, apply explicit clear flags, atomically persist, and return the reloaded public view.

- [ ] **Step 5: Remove duplicate priority logic from `config.py`**

Build effective configuration in the fixed order defaults, environment initial values, persisted runtime values, explicit request overrides. Return a newly allocated dictionary for every call and convert numeric fields once.

- [ ] **Step 6: Run repository tests**

Run: `python -m pytest tests/test_runtime_config.py -v`

Expected: all tests PASS.

### Task 3: Unify FastAPI configuration routes

**Files:**
- Create: `Analyst/tests/test_config_api.py`
- Modify: `Analyst/api_server.py`
- Test: `Analyst/tests/test_config_api.py`

- [ ] **Step 1: Write failing API tests**

Use `fastapi.testclient.TestClient`. Verify `POST /api/config` accepts the existing nested `{dataConfig, llmConfig}` body plus `dataSource`, `crawlUrl`, `tushareToken`; `GET /api/config` returns the saved values and masked statuses; `GET/POST /api/config/data-source` see the same state; missing `CONFIG_ENCRYPTION_KEY` returns HTTP 422 for a submitted secret; clear flags remove credentials.

- [ ] **Step 2: Run API tests and verify failure**

Run: `python -m pytest tests/test_config_api.py -v`

Expected: FAIL because the current model drops nested/data-source fields and the compatibility route writes `.env`.

- [ ] **Step 3: Expand and flatten the request model deliberately**

Add nested model/data objects and data-source fields to the request schema. Convert them to one normalized repository payload before calling `update_runtime_config`; do not pass masked credential placeholders.

- [ ] **Step 4: Delegate compatibility routes to the repository**

Delete `.env` file reading/writing from `/api/config/data-source`. Have both compatibility methods call the same runtime repository and return its public data-source view.

- [ ] **Step 5: Map known errors without leaking secrets**

Add FastAPI exception handlers (or route-local translation) mapping validation/encryption errors to HTTP 422 with a safe `detail`. Do not log request bodies or plaintext keys.

- [ ] **Step 6: Run API and repository tests**

Run: `python -m pytest tests/test_runtime_config.py tests/test_config_api.py -v`

Expected: all tests PASS.

### Task 4: Guarantee immediate, stable analysis snapshots

**Files:**
- Modify: `Analyst/services/analysis_runner.py`
- Modify: `Analyst/api_server.py`
- Test: `Analyst/tests/test_config_api.py`

- [ ] **Step 1: Add failing snapshot tests**

Patch the expensive model runner and capture its config. Save model A, create task A, save model B, then create task B. Assert A receives its creation-time snapshot and B receives model B. Assert a browser request without explicit overrides does not replace server values.

- [ ] **Step 2: Capture configuration at task creation**

In `start_analysis`, resolve a complete effective snapshot after sanitizing explicit overrides and store/pass that copied dictionary to `_execute_pipeline`. Do not re-read mutable runtime state inside the background job.

- [ ] **Step 3: Consume the supplied snapshot once**

Adjust `run_full_analysis`/`run_analysis_pipeline` so the already-resolved snapshot is used for model creation, paths and the returned runtime view. Keep request overrides supported, but only when fields are explicitly present.

- [ ] **Step 4: Run snapshot tests**

Run: `python -m pytest tests/test_config_api.py -v`

Expected: all tests PASS.

### Task 5: Repair frontend configuration state

**Files:**
- Modify: `frontend/src/api/configApi.js`
- Modify: `frontend/src/utils/systemConfig.js`
- Modify: `frontend/src/pages/Settings.jsx`

- [ ] **Step 1: Normalize the unified server response**

Include `dataSource`, `crawlUrl`, `apiKeyConfigured`, `maskedApiKey`, `tushareTokenConfigured`, and `maskedTushareToken` in `normalizeSystemConfig`. Make `saveSystemConfig` return the normalized configuration from the server response.

- [ ] **Step 2: Stop stale browser settings overriding the server**

Change `buildAnalyzeStartBody` to emit `stockCode`, `analysisDate`, and selected `dataSource` only by default. Add `llmConfig`/`dataConfig` solely when an explicit per-run override argument is supplied; remove the session API key path from analysis startup.

- [ ] **Step 3: Use one API path on Settings**

Load all form and data-source fields from `fetchSystemConfig`. Save both sections through `saveSystemConfig`, use its returned normalized state to refill controls, and remove direct `fetch('/api/config/data-source')` calls.

- [ ] **Step 4: Add explicit credential clearing**

Show configured/masked status beside each password input. Add confirmation buttons that submit `clearApiKey: true` or `clearTushareToken: true`; leaving an input blank sends neither the value nor the clear flag.

- [ ] **Step 5: Build and lint the frontend**

Run: `npm run build`

Expected: Vite completes successfully and creates `dist` without compile errors.

Run: `npm run lint`

Expected: exit code 0; fix only lint errors introduced or exposed in modified files.

### Task 6: Full verification and deployment documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the deployment contract**

Add `CONFIG_ENCRYPTION_KEY=<long-random-server-string>` to the real-model `.env` example. State that changing it makes existing encrypted credentials unreadable, secrets are not returned to the browser, and runtime saves apply to the next analysis without restart.

- [ ] **Step 2: Run the backend regression suite**

Run from `Analyst`: `python -m pytest tests -v`

Expected: all tests PASS.

- [ ] **Step 3: Run syntax/import checks**

Run from `Analyst`: `python -m compileall config.py api_server.py services`

Expected: exit code 0 with no syntax errors.

- [ ] **Step 4: Run frontend verification**

Run from `frontend`: `npm run build` and `npm run lint`.

Expected: both commands exit 0.

- [ ] **Step 5: Inspect persisted output safely**

Save known test credentials against a temporary configuration path, parse the JSON, and assert the plaintext strings are absent. Never print decrypted values.

- [ ] **Step 6: Record workspace limitation**

Run: `git status --short`

Expected in this workspace: `fatal: not a git repository`; report changed files directly instead of claiming commits.
