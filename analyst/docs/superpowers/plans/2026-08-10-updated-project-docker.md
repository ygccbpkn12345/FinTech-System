# AnalystVerse Updated Project Docker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the single-container deployment around the updated root `Analyst/` backend.

**Architecture:** Build the frontend in a Node stage and run its static output with Nginx in a Python 3.12.4 runtime image. Run one Uvicorn worker and rely exclusively on the updated backend for Baostock/Tushare fetching and result generation.

**Tech Stack:** Docker, Node.js 22, Vite, Python 3.12.4, FastAPI, Baostock, Tushare, Nginx

---

### Task 1: Rebuild image definition

**Files:**
- Modify: `Dockerfile`
- Modify: `.dockerignore`

- [ ] Remove the obsolete startup result-preparation script from the image.
- [ ] Install Baostock, Tushare and all FastAPI runtime dependencies.
- [ ] Exclude `docker/Analyst` from the build context.

### Task 2: Update runtime entrypoint

**Files:**
- Modify: `docker/entrypoint.sh`

- [ ] Start only one Uvicorn worker and Nginx.
- [ ] Verify Linux line endings and shell syntax through the image build.

### Task 3: Update deployment documentation

**Files:**
- Modify: `README.md`

- [ ] Explain that online fetching is implemented by the updated backend.
- [ ] Document Baostock and Tushare configuration, persistent directories and access URLs.
- [ ] Build the frontend and Docker image, then verify the health endpoint.

