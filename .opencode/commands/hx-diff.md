---
description: "Inspect a commit, range or working diff without an HX plan"
agent: orchestrator
---

Read-only inspection. Target: $ARGUMENTS

Use the plugin tool `hx_git_inspect`: `commit` for a hexadecimal SHA or HEAD reference; `range` for `<base>..<target>`; `working` when no target; `status` for concise working tree state. For a commit-specific parent diff use the immutable `parents[0]` from `action: "commit"` as the range base, not `HEAD~1` unless HEAD is demonstrably the same target. SHA~N and SHA^N are valid bounded references. Use `files` and `file` to retrieve details if the patch is truncated. Do NOT call `hx_manage verify`, require approval of an HX plan, change files, or create a worktree. The tool is bounded to read-only Git commands and doesn't need the shell tool. If unavailable, report the unavailable capability.
