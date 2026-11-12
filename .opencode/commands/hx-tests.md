---
description: "Run quality checks independently or in an approved HX worktree"
agent: orchestrator
---

WORKFLOW HX_TESTS. Run the plugin tool `hx_run_checks` for the current repository or an approved worktree. A formal HX task is NOT a prerequisite. The tool previews an immutable manifest and uses native OpenCode permissions for the exact commands, cwd, and hashes; a saved approval may be reused for the same manifest. It returns STARTED with job_id immediately. Call hx_checks_status to obtain durable RUNNING/PASS/FAIL state; repeated calls to hx_run_checks must not start duplicate builds. If the server restarts, resume polling in a new session without restarting the build. If the project lacks required gate configuration, create `.opencode/hx/quality-gates.json` using native edit permissions before previewing. In a standalone invocation, return PASS/FAIL/UNVERIFIED without claiming completion of a formal HX task. Never execute a Quality Gates CLI command through shell or slash-command interpolation. Warn that host-approved build scripts can launch subprocesses with user privileges. If the tool is unavailable, report BLOCKED. Target: $ARGUMENTS
