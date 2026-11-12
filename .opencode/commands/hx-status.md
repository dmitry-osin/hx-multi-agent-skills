---
description: "Show HX state, or clearly report no registered plan"
agent: orchestrator
---

Call `hx_manage` with `action: "status"`. No HX plan is needed: `NO_TASK` is a valid result, not an error or a reason to create a task. For a registered task report ID, status, plan hash, approvals, worktree, checks, and cycles. Do not call verify merely to display status. Request: $ARGUMENTS

When checks may be running, also call hx_checks_status for the active worktree to show RUNNING/PASS/FAIL without waiting on a long build.
