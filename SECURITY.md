# HX v5.8.0 — Security and Permissions

**Author:** Dmitry Osin

## Native OpenCode permissions

HX no longer provides an additional shell-command classifier, a permission override hook, or a shell creation/rewrite hook. OpenCode evaluates permissions for `shell` (including Git, cmd, PowerShell, Maven and Gradle), `edit`, `read`, `execute`, external directories, and MCP tools. The user chooses **Allow once**, **Allow always**, or **Deny** using OpenCode's normal interface and configured rules.

No HX agent frontmatter overrides these native tool permissions. The legacy plugin path `plugins/hx-command-guard/` is retained to avoid breaking global/local installation discovery; its plugin registers workflow tools and sanitized tool activity logs, **not** a Command Guard enforcement layer. `/hx-security-status` reports this native mode, and `/hx-security-log` displays tool events, not permission decisions.

The bundled `opencode.jsonc` has **no shell/read/edit/external-directory restrictions or hard tool-use policies**. Existing user-defined restrictions are preserved. On upgrade with `--replace-hx`, the installer removes the exact entries shipped in the previous HX configuration, including `edit:.opencode/hx/**` (which prevented `quality-gates.json` creation). It does not delete user-defined rules with other patterns, such as `git push *`. Because configuration files do not record rule authorship, an exactly identical custom rule cannot be distinguished from a legacy HX rule; review the backed-up config after migration.

## Workflow-specific consent (retained)

- `hx_approve_plan` still uses an explicit OpenCode `hx_approve` permission for each plan digest. Its tool call uses `save: []`: the plan must be accepted deliberately before implementation starts.
- `hx_run_checks` previews an immutable manifest and uses OpenCode's `hx_checks` permission. The tool now passes `save: [manifest_sha256]`, so **Allow always may be remembered for the same exact manifest**; a changed manifest requires a new decision. The preflight, worktree checks, and source revision integrity checks still apply.
- The plugin does **not** promote an existing native `allow` to `ask` for ordinary shell commands or other tools. Native OpenCode `deny` remains final.
- If the installed OpenCode client does not support the expected custom permission interaction, HX should report that limitation rather than claiming approval.

## Agent roles and limits

The seven agents still have separate responsibilities and different models. The Architect plans, Developer implements, Test Engineer runs tests, Reviewer and Security Auditor independently audit, Documentation updates docs, and Orchestrator coordinates. Their role instructions are behavioral guidance; **without restrictive tool permissions, read-only review is no longer an enforced OS-level or tool-level guarantee**. If strict isolation is required, use a separate read-only checkout or operating-system sandbox, or configure explicit native permission rules yourself.

No agent should silently claim that a command ran or that a check passed. User approval for one action does not establish successful completion of the next action.

## Quality Gate execution

The immutable manifest contains the gate argv, cwd, executable identity, project revision, and configuration digest. HX rechecks it before and after each gate. A matching permission allows the parent process; Maven, Gradle and npm may spawn subprocesses with normal account privileges. HX does not inspect or approve those child processes one by one.

By default Quality Gates run directly on the host (`ask-host`) after the native `hx_checks` permission. Optional Linux/WSL Bubblewrap isolation is still available through `hx/guard/policy.json` (`sandbox-required` or `sandbox-preferred`), but it applies **only to Quality Gates**, never to ordinary OpenCode shell calls. A project may opt into stricter gate isolation; this may cause gates to fail when Bubblewrap is unavailable. Windows users should normally retain `ask-host`.

Project-specific gate commands can be placed in `.opencode/hx/quality-gates.json`. Native OpenCode edit permissions decide whether agents may create or edit that file; the old bundled hard deny no longer exists. The Orchestrator may prepare this file when required by the approved plan. Changing the manifest invalidates previous gate results.

## Review provenance and audit logging

`hx_submit_review` accepts reports only from the dedicated reviewer and security-auditor agent sessions, validates exact source anchors and stores HMAC-associated metadata in private Git state. This provides traceability, not protection against an attacker who controls the local OS account. Independent reviews do not require a formal plan or worktree.

The diagnostic file `$(git rev-parse --git-common-dir)/hx/security/guard.jsonl` contains hashes of tool input and tool status when observable. It does not capture OpenCode permission outcomes and should not be interpreted as an approval log. Existing legacy entries may remain.

## Migration verification

After upgrading, restart the OpenCode server/session, inspect the merged configuration via `opencode debug config`, and check that no inherited HX `tool.use` denies remain. Test native UI choices on harmless shell commands, then configure a harmless Quality Gate in a disposable Git repository without secrets. If a command is still denied without a prompt, check user-defined/organization policies, session-scoped rules and plugin load order; HX no longer overrides them.

### Long-running jobs

After native permission is granted, a detached Python worker executes precisely the approved manifest SHA-256. It checks the manifest again before each gate and after completion. A server restart does not grant fresh permissions or mark tests as passed; `hx_checks_status` reports the durable result. Background jobs execute with the server user's OS rights in `ask-host` mode and may keep running after OpenCode exits; inspect job status before any manual retry.

## Windows background worker behavior (v5.8.0)

Background Quality Gates prefer a console-free GUI Python interpreter on Windows. When absent, HX uses `windowsHide: true` without detaching the console process. A non-detached worker may have different survival characteristics across server shutdown; persisted results remain authoritative, and incomplete jobs must never be treated as PASS.

## Formal review source binding (v5.8.0)

A formal review is scoped to the approved worktree and attested to its current 64-character SHA-256 revision fingerprint. The fingerprint is not a Git commit and is never accepted as a standalone target. For source-bound findings, new/untracked files are read directly from the worktree; Git targets and ranges are only for deliberately standalone audits and read source at the newer target SHA. Agents must validate source anchors and submit before running out of tool steps. Native permissions remain unchanged.

## HX v5.8.0 landing safety

`hx_land` is a dedicated mutating tool, with a native OpenCode permission rule (`hx_land: ask`). Landing is never part of `hx_manage complete`. Each phase rechecks the immutable preview digest, approved task status, original checkout branch/tip, worktree source integrity and committed tree. `git push`, forced merges, resets, forced worktree removals and branch deletion are never executed. Commit and merge run normal Git hooks, which can execute arbitrary commands; inspect local hooks and the exact preview before approving. Remote PR creation remains manual.

Legacy completed tasks may not have source-content snapshots that survive runtime upgrades. Normal landing fails; `legacy_override: true` is an opt-in manual review path with a distinct `hx_land_legacy` permission and explicit `LEGACY_MANUAL` proof label. It must not be represented as matching the original QA snapshot.
