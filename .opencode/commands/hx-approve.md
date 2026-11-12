---
description: "Human approval: explicitly approve the exact registered plan"
agent: orchestrator
---

WORKFLOW HX_APPROVE. The user invoked this slash command. Read the current plan and status using tools. Show plan title, version and full SHA-256. Then call **hx_approve_plan** (from the HX plugin), not shell or command substitutions. Its OpenCode permission prompt MUST be confirmed by the user for this exact plan. If rejected or plugin missing, STOP. After receiving APPROVED, create a Git worktree via OpenCode Code Mode `worktree_create` (request permission if needed), attach HX via `hx_manage` with `action: "attach"` and `argument` set to the worktree path, move the session using Code Mode `session_move` or ask the user to reopen OpenCode in the worktree; after the location switch call `hx_manage` with `action: "start"` and `cwd` set to the approved worktree, and only then delegate code edits. Never claim approval from the text of the user's request alone. Additional constraints: $ARGUMENTS
