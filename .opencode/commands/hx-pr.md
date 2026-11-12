---
description: "Generate a PR draft even when no HX plan exists"
agent: orchestrator
---

Use `hx_manage` with `action: "pr"` to generate a local `.hx/PR.md` draft. No HX plan is needed: the draft is clearly marked STANDALONE/UNVERIFIED without formal gates. When a completed HX task exists, include its verified gate results. No commit, push, or remote PR automatically. Read the generated draft and disclose limitations. Request: $ARGUMENTS

For a completed HX worktree that must be committed and merged, use `/hx-land` instead. `/hx-pr` never commits or pushes.
