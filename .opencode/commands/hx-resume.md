---
description: "Resume an approved task after interruption"
agent: orchestrator
---

Use `hx_manage` with `action: "verify"` and `action: "status"`. If invalid or not in approved worktree STOP. Resume only incomplete tasks using saved state; do not assume chat text is evidence. If a background Quality Gate job is active, use hx_checks_status to retrieve its persisted result without restarting Maven. Request /hx-tests again only when revision/manifest changed or the previous job reached a terminal failure. User focus: $ARGUMENTS

If the selected task is already COMPLETED, do not re-run the pipeline. Offer `/hx-land` to transfer its reviewed worktree to the original branch through separate Git commit/merge permissions.
