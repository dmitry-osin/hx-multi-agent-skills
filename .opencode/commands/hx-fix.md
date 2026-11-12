---
description: "Fix requested issues with an optional formal HX task"
agent: orchestrator
---

Scope: $ARGUMENTS

If the CURRENT checkout belongs to an approved HX task in an attached worktree, use the formal flow: inspect task state, delegate developer, request `hx_run_checks` approval and independent reviews, enforce retry limits. If no approved task exists (including DRAFT/NO_TASK), treat this as a standalone user-requested fix. Do NOT create or approve an HX plan or worktree; delegate the requested edits to developer in the current checkout, ask for unsafe command permissions, and report validation outcomes as UNVERIFIED when not run. Do not call `hx_manage cycle` or `verify` for standalone work. Never claim that a standalone fix completed HX formal gates.
