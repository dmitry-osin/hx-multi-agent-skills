# Installing OpenCode HX v5.8.0

**Author:** Dmitry Osin · **Installation modes:** global or project-local.

## Global installation — Windows PowerShell

Extract the HX archive, then open PowerShell in the directory containing `install.py`:

```powershell
py -3 .\install.py global --target "C:\Users\Dmitry\.config\opencode"
py -3 -m pip install -r "C:\Users\Dmitry\.config\opencode\hx\requirements.txt"
```

The `/hx-plan`, `/hx-approve`, and other HX commands are then available from any Git repository, including repositories without their own `.opencode/` directory. Each project's current plan is kept at `.hx/plan.md`; task history is stored in the Git common directory under `hx/`.

## Local installation — Windows PowerShell

```powershell
py -3 .\install.py local --target "C:\Users\Dmitry\sources\my-project"
py -3 -m pip install -r "C:\Users\Dmitry\sources\my-project\.opencode\hx\requirements.txt"
```

The target project must be a Git repository. All HX agents, commands, and skills are installed under `<project>/.opencode/`. Existing OpenCode user settings are merged at the value level rather than discarded.

## Linux / WSL

```sh
python3 install.py global
# Or:
python3 install.py local --target /path/to/repo
```

WSL and Windows have **separate** global OpenCode configuration directories. Install `jsonschema==4.26.0` into the Python environment that OpenCode's HX tools can access.

## Upgrades and protecting existing settings

```powershell
py -3 .\install.py global --dry-run
py -3 .\install.py global --replace-hx
```

The `--replace-hx` upgrade also backs up and removes obsolete HX quick-edit agents/commands. It switches a previous HX default agent to the built-in `build`, while preserving unrelated user-selected defaults and custom `root.md` agents. An already-open OpenCode session may retain its previously selected agent until switched or restarted.

Without `--replace-hx`, an existing HX file that differs from the packaged version blocks the update. With the option enabled, backups are stored under `.hx-install-backups/` globally or `git common-dir/hx/install-backups/` locally. The installer structurally merges `opencode.jsonc` with the supplied configuration. **Comments and formatting may change** when JSONC must be rewritten, but a backup is saved. Reinstalling does not duplicate the two HX workflow permission actions.

## Native Plan + Build (global or local)

1. Select OpenCode's built-in **Plan** primary agent and describe the change. Plans and explanations are presented in Russian.
2. Approve the plan in the same session, then switch to the built-in **Build** primary agent using the agent selector/Tab.
3. Build can edit the active checkout directly without entering the versioned HX workflow. Shell, Git, PowerShell, cmd, edit and MCP permissions follow OpenCode defaults and your own rules.
4. In new sessions, Build is the default agent unless your existing OpenCode configuration explicitly chooses a different agent.

The installer also registers the English-language policy file `hx/instructions/communication.md` as OpenCode instructions. It directs all agents, including native Plan and Build, to communicate with the user in **Russian** while keeping code comments and documentation in **English**. On global installs it uses the installed file's absolute path; on project installs it uses `.opencode/hx/instructions/communication.md`.

## Verification checklist

1. Restart OpenCode V2. Verify the Plan and Build agents follow Russian communication rules. Connect the **DeepSeek API** with `/connect`, and check model availability through `/models`.
2. Run `/hx-security-status`. Stop if the HX workflow plugin is not loaded.
3. In a disposable Git repository, run `/hx-plan Small test task`. Inspect `.hx/plan.md`, then call `/hx-approve`.
4. Approve **the specific plan** in the OpenCode UI. After the worktree is created, open a session there and run `/hx-tests`. Verify that the gate manifest is presented and can be approved for that digest.
5. Independently, in a repository with **no HX plan**, run `/hx-review HEAD` and verify both agents inspect that SHA and submit separate reports. Repeat with `HEAD~1..HEAD`, `<target-SHA>~1..<target-SHA>`, or `<base-SHA>..<target-SHA>` and with a plan left in DRAFT; neither case should trigger HX approval.
6. Test `/hx-status` (NO_TASK in a clean repository), `/hx-cost`, `/hx-diff`, and `/hx-resume` (formal tasks only). Verify that modifying source files after successful checks prevents task completion.
7. Test a dirty DRAFT checkout: `/hx-approve` must report the reason before showing a permission prompt. A tool log entry is not proof of a user approval.

## Security

In `ask-host` mode, approved commands execute on the host. On Linux/WSL, you can configure Bubblewrap with `sandbox-required` in `hx/guard/policy.json` (global) or `.opencode/hx/guard/policy.json` (local). If both installations are present, the local policy may strengthen but must not weaken the global restrictions. Do not keep secrets in disposable test worktrees.

See [README.md](README.md), [SECURITY.md](SECURITY.md), and [RELEASE_NOTES.md](RELEASE_NOTES.md).

## Independent review troubleshooting

- `hx_manage verify` on a DRAFT plan returns a deliberate `BLOCKED` error; that is not a missing Python interpreter. The plugin now forwards the detailed CLI error.
- To review a commit without approval, use `/hx-review <commit-SHA>` rather than `/hx-plan` or `/hx-approve`.
- If `hx_git_inspect` or `hx_submit_review` is unavailable, check that the HX workflow plugin loaded and that the session allows Code Mode. The `execute` permission can prompt separately from a read-only Git inspection.
- If Python is missing or the CLI reports missing `jsonschema`, install the pinned dependency in the interpreter used by the HX plugin (`HX_PYTHON` may override the interpreter).

## Review report schema (v5.8.0)

After upgrading, restart OpenCode so that the new tools are registered. Dedicated reviewer agents should call `hx_review_contract`, `hx_validate_review`, and only then `hx_submit_review`. The contract is stored at `hx/review-schema.json` in global mode or `.opencode/hx/review-schema.json` in local mode.

Every finding requires an `anchor` copied exactly from the reviewed file; a numeric `line` is optional only if the anchor uniquely identifies the line. Results now contain both `verdict` and `coverage`, and formal completion requires `APPROVED + COMPLETE` from both independent agents. Older report payloads missing `coverage` or `anchor` must be updated before resubmission. Existing stored reports are not silently rewritten.

For an approved worktree task, call `hx_review_contract({"cwd":"<worktree>"})`; it returns `review_mode: FORMAL`. Reviewer and Security Auditor must submit with `mode: FORMAL` and **without `target` or `base`**. A 64-hex workspace fingerprint is not a Git commit. The plan's 40-hex base commit will not contain new code added during implementation. For a genuinely independent Git audit use `mode: STANDALONE` and a real target commit SHA (plus base for a range). Updated agents use 48 steps to reserve time for validation and submission.

## Native tool permissions and migration

HX no longer enforces repeated shell approvals or blanket edit denials for its agents. The seven roles inherit OpenCode native permission behavior; **Allow always** is respected. The explicit approval of an HX plan remains mandatory. Quality Gate permissions may be saved per exact manifest digest. Follow [SECURITY.md](SECURITY.md) for the distinctions.

When upgrading an existing global installation, run:

```powershell
py -3 .\install.py global --target "C:\Users\Dmitry\.config\opencode" --replace-hx
```

The installer backs up `opencode.jsonc`, removes known legacy HX rules such as `tool.use edit:.opencode/hx/** deny`, and retains unrelated user rules. It cannot distinguish a user rule that exactly duplicates a former HX rule. For a local installation, use `local --target <repo> --replace-hx`. Restart OpenCode afterward.

A separate project-specific Quality Gate config can be created at `<repo>/.opencode/hx/quality-gates.json` using normal OpenCode edit permissions. Verify this in a disposable project if you previously hit `permission.rejected: edit`.

## Long-running Quality Gates

`hx_run_checks` returns a job ID immediately. Query `hx_checks_status` for progress, and use the same worktree path after an OpenCode restart. Avoid repeating the start call while a job is RUNNING. The worker's output log and durable JSON status live under the Git common directory in `hx/check-jobs/`. On Windows, configure `JAVA_HOME` and make `mvn.cmd` available to the OpenCode server before starting it.

## Landing a completed task

Install HX v5.8.0 and restart OpenCode. Open the completed worktree and run `/hx-land`. Choose the local merge or a PR draft after viewing the exact changes. The plugin requests separate native permissions for commit, merge, and optional cleanup. A local PR draft does not push to any remote. See README.md for the full sequence and legacy limitations.
