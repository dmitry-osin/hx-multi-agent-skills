# HX v5.8.0 — Verified Worktree Landing

- New `/hx-land` command and `hx_land` tool implement revision-bound preview, explicitly approved commit, separately approved local merge, local PR draft, and optional approved cleanup. No push or branch deletion.
- Commit stages only eligible source paths; HX-managed files are excluded. A completed task records a runtime-independent source digest to detect changes after reviews, including newly created files.
- Target checkout must be clean and at the original approved base; changes to the target branch block unsafe automatic merge, but a `strategy: pr` preview can still prepare a local PR draft.
- Source commit tree is compared with the resulting merged tree. Native OpenCode permission is requested separately for each mutation.
- Completed tasks from older HX runtimes without source snapshots can land only when the original workspace revision still matches the approved review; otherwise a separately approved `LEGACY_MANUAL` landing is possible only after the user reviews all diffs and accepts the missing integrity proof.
- Added regression tests for changed code, target branch advance, optional worktree cleanup, PR-only mode, and managed file exclusions.

---

# HX v5.7.3 — Reliable Formal Review Mode and Submission

November 12, 2026 · Author: Dmitry Osin

- Introduced explicit `FORMAL` / `STANDALONE` selection for `hx_validate_review` and `hx_submit_review`. In an approved HX worktree, `target` and `base` are rejected unless explicitly opting into a separate standalone Git audit.
- `hx_review_contract({cwd})` now returns the active review mode and exact invocation guidance. FORMAL reports automatically bind to the worktree revision and validate new or untracked files at the worktree, not at the plan's parent Git commit.
- Detect misuse of a 64-character HX workspace digest as Git SHA with a precise correction. Standalone ranges continue validating source anchors at **target**, not **base**.
- Increased Reviewer and Security Auditor limits from 14 to 48 steps. Their instructions reserve submission budget, prioritize `hx_validate_review` and `hx_submit_review`, and require honest PARTIAL reports if optional checks remain incomplete.
- Improved `FILE_UNAVAILABLE` diagnostics for source files introduced after the supplied commit. Added regression tests for untracked files, wrong targets, role instructions, and global-install upgrades.
- Native OpenCode permission choices, plan approval, background Quality Gates and independent review attestation are unchanged.

## Previous release: v5.7.2 — Windows background checks

- Fixed the visible Windows console opened by the background Quality Gates launcher (`detached: true` on console executables).
- Prefer the matching windowless interpreter (`pyw.exe` or `pythonw.exe`) for background workers on Windows. If unavailable, launch with `detached: false` and `windowsHide: true` to avoid a new detached console window.
- Preserve detached process groups on Linux and macOS; Python's `CREATE_NO_WINDOW` handling remains active for Maven/CMD child processes on Windows.
- Added regression tests for Windows GUI launcher selection, console fallback, and Unix behavior. Runtime visibility still requires real Windows verification.

## Previous release: v5.7.1



### Quality Gates reliability fix (v5.7.1)

- Run long builds in a detached worker; avoid synchronous Node execution blocking the OpenCode event loop.
- Add persisted checks job status and `hx_checks_status`, safe to query after server restart.
- Keep the repository state lock free while builds are running, then revalidate the manifest before recording PASS.
- Fix Windows Maven auto-discovery to use `cmd.exe /d /c mvn.cmd` (or `mvnw.cmd`).
- Preserve native OpenCode permission prompts and manifest-specific saved approvals.


November 12, 2026 · Author: Dmitry Osin

- Removed HX's permission-evaluation and shell-execution hooks. Native OpenCode **Allow once / Allow always / Deny** choices now govern shell (including Git, PowerShell and cmd), edit, read, Code Mode, and MCP tools.
- Removed bundled hard-deny policies for `.opencode/hx/**`, agents, configuration, `.env` and CLI approval commands. The installer removes exact legacy HX rules on upgrade while preserving unrelated user-defined restrictions and backing up previous configuration.
- All seven HX roles now inherit native tool permissions; read-only reviewers remain bound by agent instructions, not an enforced sandbox.
- Preserved the full HX agent orchestration, plan hash and approval checkpoint, isolated worktree, immutable Quality Gate manifests, independent review reports, and documentation workflow.
- `hx_approve_plan` still needs an explicit plan-specific approval. `hx_run_checks` now supports OpenCode's persistent approval for the **same manifest digest**; changed manifests need reapproval.
- The existing `hx-command-guard` plugin path is retained as a compatibility name. It now only registers HX workflow tools and sanitized tool activity, and does not override normal permissions.
- Updated global/local migration tests and troubleshooting for project `.opencode/hx/quality-gates.json` editing.

## Previous workflow and review improvements

November 12, 2026 · Author: Dmitry Osin

## Robust commit ancestry inspection (previous improvement)

- `hx_git_inspect` now accepts a single bounded ancestry suffix on a hexadecimal commit SHA (e.g., `<SHA>~1`, `<SHA>^2`), not just on HEAD. The tool still uses argument vectors, `--end-of-options`, and a strict input allowlist; arbitrary revision expressions remain rejected.
- `action: "commit"` returns an ordered `parents` list of immutable SHAs, enabling correct parent-based review when the requested commit is not HEAD (and for merge commits).
- Reviewer/Orchestrator instructions require choosing the actual parent of the requested SHA, never guessing `HEAD~1`.
- `file` inspection now honors an explicit `base` and returns that file's diff; previously it silently ignored `base` and returned source code even when the agent requested a comparison. With no `base`, `file` continues to return source content.
- Added regression tests for explicit SHA ancestors, HEAD differing from the target commit, per-file range diffs, and merge commit parent selection.

## HX v5.6.0 — reliable source-backed review reports

- Added `hx_review_contract`, which returns the **live** authoritative JSON Schema and an example to reviewer/security-auditor agents. It also explains the verdict/coverage rules.
- Added `hx_validate_review` for non-persistent preflight checks. `hx_submit_review` performs the same preflight before signing and the Python persistence layer validates again.
- Every finding requires an exact, source-backed `anchor`. If `line` is omitted, HX resolves it only when the anchor appears on exactly one line. When a line is supplied, its content must contain the anchor. Unknown or ambiguous locations are rejected rather than guessed.
- Report fields now include `coverage: COMPLETE | PARTIAL | BLOCKED` independently from `verdict: APPROVED | CHANGES_REQUESTED | UNVERIFIED`. Coverage rules prevent contradictory reports. `APPROVED + PARTIAL` can describe reviewed scope while formal HX task completion still requires `COMPLETE` from both reviewers.
- Validation errors now contain field paths, machine-readable issue codes, and actionable messages.
- Upgraded regression tests for bad line numbers, nonexistent anchors, partial coverage, source binding, standalone and formal review submission.

## HX v5.5.1

- `hx_git_inspect` accepts `HEAD`, `HEAD~N`, and `HEAD^N` in addition to hexadecimal SHAs, then returns immutable full SHAs. Arbitrary Git expressions remain blocked.
- Standalone signed reviews canonicalize symbolic Git references to fixed commit SHAs before passing targets to Python.
- Child processes started by the HX plugin and Python runtime now suppress Windows console windows.
- Added tests for reference resolution, rejection of unsafe references, and stable standalone report targets.

## v5.5.0: standalone review and approval diagnostics

- `/hx-review` and `/hx-audit` no longer require `/hx-plan`, `/hx-approve`, a task, or a worktree. They support an exact hexadecimal commit SHA, `<base>..<target>` SHA range, or working-tree changes.
- Added the bounded read-only `hx_git_inspect` tool for commit/range patch lookup, file enumeration, and fetching a single file from the target commit. It uses Git argument vectors without a command shell; unavailable Code Mode tools now produce an explicit BLOCKED/UNVERIFIED result instead of implicit approval workflow.
- Reviewers and security auditors submit their own signed, JSON-schema-validated standalone reports into `git common-dir/hx/standalone-reviews/` without touching application code or creating `.hx/plan.md`.
- Added approval preflight *before* the user permission prompt; a dirty checkout, stale plan, or missing snapshot reports the real error without asking for unusable approval. The CLI repeats checks when committing approval.
- Python CLI exceptions now retain structured details through the plugin wrapper; `permission: ask` is not interpreted as proof of user rejection.
- `/hx-status`, `/hx-cost`, `/hx-diff`, `/hx-tests`, `/hx-pr`, `/hx-fix` support standalone tasks. `/hx-approve` and `/hx-resume` remain formal-only. `/hx-plan` remains the formal entry point.
- Added new Python and JavaScript regression tests for SHA and range reviews, DRAFT-plan independence, error transparency, and preflight behavior.

## v5.4.1: native Build instead of a custom shortcut agent

- Removed the custom quick-edit primary agent and slash command. The built-in OpenCode `build` agent is now the default for newly installed HX configuration.
- Added safe cleanup for retired HX agent and command files during `--replace-hx` upgrades, including backup before deletion. User-owned `root.md` files are preserved unless marked as an HX agent.
- Kept the full HX workflow, Command Guard, global/local installation, and Russian-language conversations via shared instructions.
- Retained the existing development, approval and review subagents for the formal HX workflow.

## Installation and runtime

- Added a unified installer, `install.py global|local [--target PATH] [--dry-run] [--replace-hx]`, with structural JSONC merging, collision protection, and backups.
- Added a global layout under `~/.config/opencode/{agents,commands,skills,plugins,hx}`; no HX bundle is required in individual Git repositories.
- Centralized runtime path discovery and Python interpreter selection for Windows, Linux, and WSL.
- Commands now call registered tools including `hx_manage`, `hx_guard_info`, and dedicated approval, quality-check, and review tools.
- Task plans and history stay isolated per Git repository; global HX files are not copied into task worktrees.
- Local HX support files can still be copied into worktrees when absent from Git.
- When both modes are installed, the project-local Guard takes precedence; project settings must not weaken the global sandbox policy.
- Revision checks include changes to a globally installed HX runtime.
- Added tests for both installation modes, repeated installation, global worktrees, and simulated global plugin loading.

## Security and audit corrections

### Critical (P0)

- **P0-01:** Removed `!` shell expansion from HX slash commands; `/hx-approve` routes through the `hx_approve_plan` permission request.
- **P0-02:** Quality Gates execute against an approved manifest, with required sandbox enforcement when configured and a separate approval request for host execution.
- **P0-03:** Revision hashing includes Git `HEAD`, the index, tracked and untracked project files, and relevant local HX configuration, including ignored files.
- **P0-04:** Unknown MCP/custom tools request permission regardless of tool name.

### High (P1)

- **P1-01:** Task IDs combine Unicode-safe slugs with UUID suffixes.
- **P1-02:** Checkout state is task-bound, CLI mutations use a Git-common `state.lock`, and writes are atomic.
- **P1-03:** HX support-file copying into worktrees detects conflicts and excludes untracked support files from Git status.
- **P1-04:** Bubblewrap avoids mounting the entire host root or home directory; `HOME` and the process environment are isolated.
- **P1-05:** Independent review reports use JSON Schema Draft 2020-12 and additional domain validation.
- **P1-06:** Quality Gates are bound to a SHA-256 manifest and recheck project files before and after execution.
- **P1-07:** Reviewer and Security Auditor submit session-bound, HMAC-authenticated reports through plugin tools. This does not prove review quality or protect against a host-level attacker.

### Medium (P2)

- **P2-01:** Removed the unnecessary `@opencode/plugin` npm dependency; the local plugin exports the V2 `{id, setup}` object.
- **P2-02:** Git status uses `--porcelain=v1 -z`, including Unicode names and renames.
- **P2-03:** Supports multiple Maven, Gradle, and npm roots, plus explicit SQL gate examples. Absent gates return `UNVERIFIED`.
- **P2-04:** Added and refreshed the root README, setup instructions, security guide, and internal architecture guide.

## Additional safeguards

- Quality Gates cannot receive `PASS` when project files or their manifest change during execution.
- Internal state files receive restricted permissions on POSIX systems.
- Worktree support-file copying rejects suspicious symlinks.

## Validation and platform limitations

Local Python/Node tests and JavaScript plugin API simulation cover the changes above. Real OpenCode V2 permission dialogs, DeepSeek API access, Windows/WSL behavior, and Bubblewrap execution must be validated on the target installation. Sandbox isolation is available only on Linux/WSL with Bubblewrap; a plugin cannot constrain arbitrary programs started directly by the operating-system user.

See [AUDIT_FIXES.md](AUDIT_FIXES.md) for the issue-by-issue resolution matrix and acceptance checks.

