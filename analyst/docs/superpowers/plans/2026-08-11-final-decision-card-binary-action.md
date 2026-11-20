# Final Decision Card Binary Action Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show only 买入/观望 and hide position inside `FinalDecisionCard` without changing stored decision data or other pages.

**Architecture:** Put display-only action normalization in a dependency-free utility and consume it exclusively from `FinalDecisionCard`. Remove position rendering from both compact and full card layouts while leaving the input object untouched.

**Tech Stack:** React 19, JavaScript ES modules, Node test runner, Vite.

---

### Task 1: Define the card display model

**Files:**
- Create: `frontend/src/utils/finalDecisionDisplay.js`
- Create: `frontend/src/utils/finalDecisionDisplay.test.js`

- [ ] Write tests asserting `谨慎买入`, `买入`, `Buy`, and `Cautious Buy` normalize to `买入`; `观望`, `Hold`, empty, and unknown values normalize to `观望`; returned display data has no position property.
- [ ] Run `node --test src/utils/finalDecisionDisplay.test.js`; expect failure because the utility does not exist.
- [ ] Implement `buildFinalDecisionDisplay(decision)` to return `{ action, actionEn }`, with `actionEn` equal to `Buy` or `Hold`.
- [ ] Re-run the focused test; expect all cases to pass.

### Task 2: Apply the display model and remove card position UI

**Files:**
- Modify: `frontend/src/components/FinalDecisionCard.jsx`

- [ ] Import and use `buildFinalDecisionDisplay`, replacing raw action labels in both card layouts.
- [ ] Remove the compact `仓位` tag, compact `建议仓位` metric, and full `建议仓位` metric without modifying `decision.position` elsewhere.
- [ ] Run `rg -n "仓位|position" frontend/src/components/FinalDecisionCard.jsx`; expect no matches.
- [ ] Run the focused test and `npm.cmd run build`; expect success.

### Task 3: Frontend regression verification

**Files:**
- Verify only.

- [ ] Run all frontend test scripts plus `src/utils/nonblockingPipeline.test.js` and the new focused test.
- [ ] Run `npm.cmd run build`; expect exit code 0, allowing the existing chunk-size warning.
