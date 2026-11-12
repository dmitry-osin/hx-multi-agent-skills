---
description: "Independent security audit of a commit, range, or workspace"
agent: orchestrator
---

WORKFLOW HX_AUDIT. User target: $ARGUMENTS

This is a standalone READ-ONLY audit. Never require `/hx-plan`, `/hx-approve`, a worktree or task verification. Inspect the commit via `hx_git_inspect(action: "commit", target: "<sha-or-HEAD-ref>")`. Its `parents` array contains immutable parent SHAs; for a single-commit parent diff use `parents[0]`, NOT a guessed `HEAD~1`. SHA~N and SHA^N references are supported with a bounded numeric suffix. Inspect a range via `hx_git_inspect(action: "range", base: "<ref>", target: "<ref>")`, or working changes via `action: "working"`. Do not treat a truncated patch as complete: inspect additional files using `hx_git_inspect(action: "file", ...)` (with `base` for a per-file diff or without it for target source). Delegate the resolved SHA(s) to `security-auditor`; it must submit its own report via `hx_submit_review` using those fixed SHA(s). No file edits or exploits. If required tools are absent, explain which tool is unavailable instead of creating an HX task.

Before each subagent submits, require it to call `hx_review_contract` followed by `hx_validate_review`. It must use exact source anchors, verified lines (or omit line), and report separate `coverage` and `verdict`; never make up locations to satisfy a validator.

For an active, approved HX task in its worktree, delegate a **FORMAL** review: call `hx_review_contract` with worktree `cwd` and require each reviewer to call `hx_validate_review` and `hx_submit_review` with `mode: "FORMAL"` and **no** `target` or `base`. A 64-character workspace revision is not a Git commit. The task base commit cannot be used to inspect newly added files. For independent Git reviews, use `mode: "STANDALONE"` with the requested commit SHA/range. Prioritize submission before optional deep exploration.
