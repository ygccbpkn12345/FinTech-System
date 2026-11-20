# AnalystVerse Offline Image Transfer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document a reproducible tar-and-SCP deployment workflow for the Linux AMD64 image.

**Architecture:** Export the locally loaded Docker image as a tar archive, verify its checksum, transfer it over SSH, and import it into the remote Docker daemon. Keep secrets and persistent data outside the archive.

**Tech Stack:** Docker Buildx, Docker save/load, SCP, SSH, SHA-256

---

### Task 1: Protect the build context

**Files:**
- Modify: `.dockerignore`

- [ ] Exclude `*.tar` and `*.tar.gz` image archives.

### Task 2: Document offline transfer

**Files:**
- Modify: `README.md`

- [ ] Add local build, architecture inspection, tar export and checksum commands.
- [ ] Add SCP upload, server checksum, Docker load and image inspection commands.
- [ ] Add first deployment and safe container replacement commands.
- [ ] Add health-check and browser access verification.

