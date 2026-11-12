# Manual OpenCode V2 acceptance checklist

The unit tests emulate OpenCode V2 plugin APIs but cannot prove actual UI behavior.

- [ ] Local V2 plugin loads; `/hx-security-status` accurately identifies this session.
- [ ] `/hx-plan` creates only `.hx/plan.md` and records a draft.
- [ ] `/hx-approve` invokes `hx_approve_plan`; Reject leaves DRAFT; Allow once changes it to APPROVED.
- [ ] Worktree creation/attach leaves app tree unchanged and HX bundle untracked files excluded.
- [ ] `/hx-tests` shows exact argv/cwd/executable digest; Reject never runs subprocess.
- [ ] Simulated manifest tamper between preview and execution is refused.
- [ ] Native OpenCode permission choices (including prior Allow always) control MCP tools such as `database_query`; HX does not force ASK.
- [ ] `reviewer` and `security-auditor` record own signed reports; orchestrator cannot impersonate them.
- [ ] `complete` blocks on source changes, stale report, unverified checks or missing session provenance.
- [ ] WSL/Linux Bubblewrap correctly hides `$HOME/.ssh` and root-only secrets; fail closed if unavailable.
- [ ] No real credentials or destructive commands used during acceptance testing.

## v5.3 — dual installation manual acceptance

- [ ] Global install on Windows at `%USERPROFILE%\.config\opencode`; config loaded without any project `.opencode` folder.
- [ ] Global `hx_manage` and `hx_guard_info` are visible in two independent Git repos. Task states stay independent.
- [ ] OpenCode native permissions apply to shell and MCP tools; HX only requests plan and manifest-specific approval.
- [ ] OpenCode Code Mode `worktree_create` and `session_move` work with the approved task; no implementation starts in original checkout.
- [ ] A global-only worktree does not get global agent/command/plugin files copied into the project.
- [ ] Local project `install.py local` works with existing `opencode.jsonc` and `.opencode/opencode.jsonc` (inspect migrated permissions/policies).
- [ ] Global + local plugin present: one local HX plugin handles project; Quality Gate sandbox settings are independent of native OpenCode tool permissions.
- [ ] On Windows native, Python launcher `py -3` resolves and no Linux Bubblewrap command is invoked in `ask-host`.
- [ ] On WSL, global settings use Linux `~/.config/opencode`, not Windows directory implicitly.
- [ ] No real credentials, production repositories, destructive commands or remote changes used in acceptance testing.

## HX v5.7.2 background Quality Gates

- [ ] Run a Maven reactor test gate and confirm `hx_run_checks` returns STARTED promptly, not only after build completion.
- [ ] Confirm OpenCode remains responsive while the Maven process is running.
- [ ] Restart the OpenCode UI/server while checks are RUNNING; ensure the worker persists and `hx_checks_status` returns a terminal result afterward.
- [ ] Confirm repeated `hx_run_checks` calls do not launch duplicate concurrent builds.
- [ ] Confirm `hx_manage status` remains responsive during the build and transitions to VERIFYING only after PASS.
- [ ] Confirm `JAVA_HOME`, `PATH`, and `mvn.cmd` are visible to the OpenCode server on Windows.
- [ ] Confirm edited sources or changed gate manifest prevent PASS; no silent workaround of native permissions.

## HX v5.7.2 Windows console verification

- Launch a background Maven Quality Gate from OpenCode on Windows; verify no Python/CMD console window appears.
- Verify `hx_checks_status` changes from `RUNNING` to `PASS` or `FAIL` and logs are written.
- Test with and without `pyw.exe`/`pythonw.exe` available and after restarting OpenCode.

## HX v5.8.0 formal review routing

- [ ] In an active, approved worktree, `hx_review_contract({cwd})` returns `review_mode=FORMAL`.
- [ ] Reviewer and Security Auditor call `hx_validate_review` and `hx_submit_review` with `mode=FORMAL`, `cwd` and `report`, omitting `target/base`.
- [ ] Findings referencing newly created untracked files pass anchor preflight and are persisted against current worktree revision.
- [ ] A supplied 64-hex workspace digest as standalone Git `target` is rejected with actionable mode guidance; plan base SHA cannot silently replace target.
- [ ] An intentional independent Git review in an active worktree uses `mode=STANDALONE` and source anchors at the target commit.
- [ ] Both agents preserve enough step budget to validate and submit their own report before finishing optional investigation.


## HX v5.8.0 landing

- Complete a real task; invoke `/hx-land` from its approved worktree. Confirm preview and only explicitly selected project files.
- Deny commit permission and verify neither checkout is modified. Allow commit; verify only the worktree branch advanced.
- Verify a separate merge permission prompt, including exact target branch and SHA. Deny it; the original branch must not change.
- Allow merge; verify source/merged trees identical, task `landing.status=MERGED` and no remote push.
- Test refusal after modification of approved files and after advancing the original target branch.
- Test optional cleanup from original checkout; confirm the source branch remains.
- Test older completed tasks whose workspace revision cannot be reconstructed after updating the global HX installation.
