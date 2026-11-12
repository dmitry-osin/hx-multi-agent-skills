---
description: "Safely land a completed HX task into the original checkout, with separate native approvals"
agent: orchestrator
---

WORKFLOW HX_LAND. Only for an already COMPLETED HX task; do not reapprove its plan or redo checks simply to land it.

1. From the completed HX worktree, call `hx_manage` with `action: "status"` and confirm COMPLETED. Then call `hx_land` with `action: "preview"` and optionally `target_branch`. Choose `strategy: "pr"` if the target branch advanced and PR preparation is wanted. Present the complete list of eligible changed files, source/target branches, original base, digest, and warnings to the user. Do not assume that the default branch is `main` or `develop`.
2. Obtain the user's explicit authorization to commit. Call `hx_land` with `action: "commit"` and the exact `manifest_sha256` returned by preview. The plugin requests native OpenCode permission; rejection means STOP. This step stages only reviewed project files, creates a local commit, and does not push.
3. Call `hx_land` with `action: "preview"` again for a separate immutable MERGE manifest. Show target branch and exact source/target commits; ask the user whether they want local merge or PR preparation. Do not silently merge merely because the commit succeeded.
4. If local merge is selected, call `hx_land` with `action: "merge"` and the new `manifest_sha256`. This prompts for separate OpenCode permission, merges into the currently checked-out original branch, and verifies the merged Git tree. No push. If the target branch advanced after commit, choose `action: "pr"` directly for a local PR draft. If it advanced before commit, re-preview with `strategy: "pr"`; never force/reset/rebase.
5. If PR is selected, call `hx_land` with `action: "pr"` after explicit authorization. It creates a local `.hx/PR.md` draft; it does not push or open a remote PR. Explain that pushing/opening a remote PR needs a separate user-approved action in OpenCode.
6. Worktree cleanup is optional and never automatic. After a successful merge, switch the OpenCode session to the original checkout, get confirmation, and call `hx_land` with `action: "cleanup"` and `cwd` set to the original checkout. No `--force`; the source branch remains until the user deletes it manually.

For tasks completed under older HX versions, the first preview may refuse because HX runtime changes invalidate historical fingerprints. Explain this explicitly. Only after the user reviews all diff files and requests a manual legacy landing may you call preview/commit with `legacy_override: true`. Such a commit requests `hx_land_legacy` permission and must be marked `LEGACY_MANUAL`, never VERIFIED. Do not invent landing success or bypass missing HX evidence. Never run `git push`, delete branches, or remove a worktree without separately approved user action. Use OpenCode native tool permissions; HX owns only the landing workflow and its integrity checks. User request: $ARGUMENTS
