# AnalystVerse Linux AMD64 Image Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deployment image explicitly target Linux x86-64.

**Architecture:** Pin both Docker build stages to `linux/amd64` and make deployment commands state the same platform. Keep all application runtime behavior unchanged.

**Tech Stack:** Docker BuildKit/Buildx, Linux AMD64, Node.js, Python

---

### Task 1: Pin image architecture

**Files:**
- Modify: `Dockerfile`

- [ ] Keep both `FROM` instructions platform-neutral and set the target in the Buildx command.
- [ ] Verify no empty or redundant platform expression remains.

### Task 2: Update build and run documentation

**Files:**
- Modify: `README.md`

- [ ] Use `docker buildx build --platform linux/amd64 --load` for image construction.
- [ ] Add `--platform linux/amd64` to deployment run examples.
- [ ] Verify the frontend production build still succeeds.
