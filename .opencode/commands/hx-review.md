---
description: "Review a Git commit, range, or current changes without requiring an HX plan"
agent: orchestrator
---

WORKFLOW HX_REVIEW_ONLY. This is an INDEPENDENT read-only audit; a formal HX plan, approval, task verification, and worktree are NOT required. Do NOT create a draft, call `hx_manage verify`, call `hx_approve_plan`, or invoke `/hx-plan` or `/hx-approve`.

Target: $ARGUMENTS

If the target is a Git commit SHA, `HEAD`, or a bounded ancestry expression such as `<SHA>~1`, `<SHA>^2`, `HEAD~N`, call `hx_git_inspect(action: "commit", target: "<ref>")`. It returns immutable `sha` and `parents` (ordered, first parent at index 0). **To review one commit against its actual parent, use `parents[0]` from this result**; never guess that `HEAD~1` is the parent of an arbitrary target SHA. For a range `<base>..<target>` use `action: "range"` with two separately resolved SHAs or supported bounded references. Without a target, call `action: "working"` to inspect the workspace. This tool runs bounded read-only Git commands without shell access. If output is truncated, use `files` to enumerate paths and `file` with `target` for source or with `base` and `target` to retrieve a per-file diff. Report remaining limitations. Do not claim full inspection of truncated data.

Use the resolved SHA (`sha`, `base`, `target`) returned by `hx_git_inspect` for all downstream subagent calls and for `hx_submit_review`. Never pass a moving symbolic reference such as `HEAD` as the recorded review target.

Delegate INDEPENDENTLY to `reviewer` and `security-auditor`, passing the exact target, scope and relevant commit diff; each must inspect evidence directly and submit its own structured report via `hx_submit_review`, setting `target` (and `base` for ranges). For no target, omit both fields. Provenance and report persistence are managed by the plugin. Do not edit project code or create a worktree. Never invent reports. If Git inspection or Code Mode tools are unavailable, report BLOCKED/UNVERIFIED with the exact missing capability; do not reroute into a formal plan approval.

Before each subagent submits, require it to call `hx_review_contract` followed by `hx_validate_review`. It must use exact source anchors, verified lines (or omit line), and report separate `coverage` and `verdict`; never make up locations to satisfy a validator.

For an active, approved HX task in its worktree, delegate a **FORMAL** review: call `hx_review_contract` with worktree `cwd` and require each reviewer to call `hx_validate_review` and `hx_submit_review` with `mode: "FORMAL"` and **no** `target` or `base`. A 64-character workspace revision is not a Git commit. The task base commit cannot be used to inspect newly added files. For independent Git reviews, use `mode: "STANDALONE"` with the requested commit SHA/range. Prioritize submission before optional deep exploration.
