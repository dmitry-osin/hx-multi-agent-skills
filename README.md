# OpenCode HX v5.8.0 — DeepSeek Multi-Agent Workflow

**Author:** Dmitry Osin  
**Version:** 5.8.0 · November 13, 2026  
**Purpose:** Plan-approved development, separate implementation and review agents, native OpenCode permissions, and Quality Gates.


## Standalone code reviews (no approved plan required)

For a single commit, run `/hx-review HEAD` or `/hx-review <Git-SHA>`, for a range use `/hx-review HEAD~1..HEAD` or `/hx-review <base-SHA>..<target-SHA>`, and without arguments `/hx-review` reviews the current checkout. `/hx-audit` applies the same targeting rules to security-only checks. These **do not run `/hx-plan`, `/hx-approve`, or create an HX worktree**. The `orchestrator` delegates to independently configured `reviewer` and `security-auditor` agents. Their submitted reports are stored under the repository's private Git common directory at `hx/standalone-reviews/`. No application files are modified by review tools. A pending `DRAFT` plan does not block a standalone commit review.

Read-only commit inspection is available through the plugin tool `hx_git_inspect`, with the actions `commit`, `range`, `working`, `status`, `files`, and `file`. It accepts SHA/HEAD references and bounded ancestry expressions (`<SHA>~N`, `<SHA>^N`, `HEAD~N`, `HEAD^N`); arbitrary expressions are rejected. The `commit` action returns `parents` as an ordered array of immutable parent SHAs. For a parent diff of an explicit SHA use `parents[0]`; do not assume that `HEAD~1` belongs to the requested commit. Resolved full SHAs are used for review delegation and persistence. The `file` action without `base` returns target source; when `base` is supplied it returns a bounded per-file diff and identifies the resolved `base`. If an inspection is truncated, inspect the necessary files individually and describe remaining limitations; never mark uninspected content as reviewed. The `reviewer` and `security-auditor` call `hx_submit_review` in their own sessions using the same `target` and optional `base` inputs; the report schema is validated before persistence. On clients that cannot expose Code Mode/plugin tools, this workflow reports `BLOCKED`/`UNVERIFIED` rather than generating a formal plan.

### Structured reviews and source-backed findings

Before writing a review report, `reviewer` and `security-auditor` call `hx_review_contract` to obtain the exact installed JSON Schema and a valid example. They use `hx_validate_review` to preflight the report, then `hx_submit_review` to submit it. The latter repeats validation before signing and again at persistence.

**Formal HX task reviews:** in the approved worktree, call `hx_review_contract` with that worktree's `cwd` and read `review_mode: FORMAL`. Both agents must call `hx_validate_review` and `hx_submit_review` with `{ "cwd": "<approved-worktree>", "mode": "FORMAL", "report": ... }` and **omit** `target` and `base`. The 64-character workspace SHA-256 is an HX revision fingerprint, not a Git commit. The 40-character parent/base Git SHA does not contain newly created implementation files; passing it as a review target would produce `FILE_UNAVAILABLE` errors. Formal report source anchors are validated against the actual worktree, including untracked source files. HX signs the current workspace revision automatically.

**Independent Git reviews:** supply `mode: STANDALONE` and an immutable Git `target` SHA, with `base` only for a range. Source anchors are validated at the target commit, not at the parent/base. If an approved task is active and an independent Git review is intentional, `mode: STANDALONE` must be explicit. `hx_review_contract` reports the appropriate default mode from the requested `cwd`.

Both reviewers now have a 48-step budget and must reserve the final steps for validation and signed submission; optional exploration cannot take precedence over recording a truthful review. An agent that runs out of steps without `hx_submit_review` has not submitted a report.

An example report without findings:

```json
{
  "verdict": "APPROVED",
  "coverage": "COMPLETE",
  "scope": "Inspected the committed change and associated tests",
  "limitations": [],
  "findings": []
}
```

Findings require `id`, uppercase `severity` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`), relative `file`, an **exact source-line substring** in `anchor`, `evidence`, and `recommendation`. `line` is optional: if omitted HX resolves it only when the anchor matches exactly one line. A supplied line must match the same anchor at the reviewed revision. `symbol` is optional human-readable context; it does not replace evidence anchoring. Fabricated line numbers or source fragments are rejected. Reviewers must disclose inaccessible files in `limitations`, not invent findings.

`coverage` describes completeness independent from the verdict. `COMPLETE` must have no limitations; `PARTIAL` and `BLOCKED` must list them. `APPROVED + PARTIAL` is valid for the inspected scope but **cannot close a formal HX task**. The final state requires both reviewer reports to have `APPROVED + COMPLETE`, successful Quality Gates and identical source revisions. A `BLOCKED` report cannot be `APPROVED`; a report with unresolved CRITICAL/HIGH/MEDIUM findings cannot be `APPROVED`.

The CLI returns detailed JSON issues (for example `$.findings[0].anchor [ANCHOR_MISMATCH]`) rather than only a generic `Command failed`. These checks enforce source alignment, not the truth of a reviewer's reasoning.

### Command dependencies

| Without a formal HX task | Requires an approved task or explicit planning |
| --- | --- |
| `/hx-review`, `/hx-audit`, `/hx-diff`, `/hx-cost`, `/hx-status`, `/hx-tests`, `/hx-fix`, `/hx-pr`, `/hx-security-status`, `/hx-security-log` | `/hx-approve`, `/hx-resume`, `/hx-land` (requires COMPLETED); `/hx-plan` creates a task by design |

`/hx-status` returns `NO_TASK` when no task is registered. `/hx-cost` does not access billing: it only reports HX's manually entered token estimates, if any. `/hx-tests` can independently run configured Quality Gates with explicit permission and without claiming formal task completion. `/hx-pr` without a completed task is an `UNVERIFIED` local draft.

`hx_approve_plan` runs an approval preflight before requesting consent. If the checkout is dirty, the registered plan has changed, or its snapshot is missing, it reports a useful error instead of triggering a permission prompt that cannot succeed. Even a successful permission request does not itself prove the CLI accepted the plan: the final `APPROVED` result must come from the CLI, which rechecks preconditions. HX does not intercept native OpenCode permission choices; permission decisions remain managed by OpenCode.

## Architecture

- **Architect — DeepSeek Pro:** examines the codebase, writes `.hx/plan.md`, registers the plan, and does not modify application code.
- **Orchestrator — DeepSeek Pro:** coordinates plan approval, an isolated Git worktree, quality checks, and review handoffs.
- **Developer — DeepSeek Flash:** implements the approved plan.
- **Test Engineer — DeepSeek Flash:** creates and maintains tests.
- **Reviewer — DeepSeek Pro:** performs an independent code review; only this agent can submit a `review` verdict.
- **Security Auditor — DeepSeek Pro:** performs an independent security assessment; only this agent can submit a `security` verdict.
- **Documentation — DeepSeek Flash:** maintains documentation and changelogs.

Included skills: `hx-java`, `hx-kotlin`, `hx-tests`, `hx-security`, `hx-sql`.

## Installation: two independent modes

**Requirements:** OpenCode V2, Git, Python 3.11+ with the `jsonschema` package (installation commands below). Node.js is needed to run local JavaScript tests, but not to install HX workflow tools. HX uses the DeepSeek API directly: configure the API key through OpenCode's `/connect` command. No API key is included in this archive.

### Option A: global installation for all projects

In Windows PowerShell, extract the ZIP to any temporary directory and run from that directory:

```powershell
py -3 .\install.py global --target "C:\Users\Dmitry\.config\opencode"
py -3 -m pip install -r "C:\Users\Dmitry\.config\opencode\hx\requirements.txt"
```

The global directory will look like this:

```text
%USERPROFILE%\.config\opencode\
├── opencode.jsonc
├── agents\
├── commands\
├── skills\
├── plugins\hx-command-guard\
└── hx\                   # CLI, guard, templates, default quality configuration
```

Linux / WSL:

```bash
python3 install.py global
python3 -m pip install -r ~/.config/opencode/hx/requirements.txt
```

The WSL global configuration lives in Linux at `~/.config/opencode`, not automatically in the Windows configuration directory. If `pip` requires a virtual environment, install `jsonschema==4.26.0` in the Python environment used by the plugin. You can configure that interpreter explicitly using `HX_PYTHON`.

After a global installation, open OpenCode from any Git repository. The repository **does not need its own `.opencode/` directory**: HX loads its agents, commands, skills, and workflow plugin from the global location.

### Option B: local installation for a single project

In Windows PowerShell, run from the extracted package directory:

```powershell
py -3 .\install.py local --target "C:\Users\Dmitry\sources\my-project"
py -3 -m pip install -r "C:\Users\Dmitry\sources\my-project\.opencode\hx\requirements.txt"
```

Linux / WSL:

```bash
python3 install.py local --target /path/to/git-project
python3 -m pip install -r /path/to/git-project/.opencode/hx/requirements.txt
```

Local mode installs into `<project>/.opencode/` and merges the OpenCode configuration. It does not create `.hx/` until the first task. Only the locally installed HX bundle is copied into a Git worktree when necessary; **a global HX installation is never copied into worktrees**.

### Safe installation and upgrades

```powershell
py -3 .\install.py global --dry-run
py -3 .\install.py global --replace-hx
```

- If a destination HX file already exists with different content, the installer **stops**. Use `--replace-hx` to update an existing HX installation. Replaced global files are backed up under `.hx-install-backups/<timestamp>/`; local backups go into the private Git common directory at `hx/install-backups/<timestamp>/`, where they do not pollute `git status`.
- The installer structurally merges `opencode.json` or `opencode.jsonc` with the HX configuration. Existing model, MCP, provider, and other user-defined settings remain in place; repeated installation does not duplicate HX rules. **Comments and formatting in existing JSONC may be lost when it is rewritten**, but a backup of the original is retained. For a local installation, an existing `.opencode/opencode.json` or `.opencode/opencode.jsonc` is also recognized.
- Unsupported or malformed configuration files fail without being overwritten. Use `--dry-run` to inspect planned modifications, and review permission rules after installation.
- To replace a previous HX installation, run the installer with `--replace-hx`. This backs up and deletes obsolete shortcut agent/command files and migrates the former HX default to the built-in `build`. An unrelated personal `root.md` is left untouched.
- When both global and local HX are present, **the local HX workflow plugin takes precedence** in that project, for tool registration. Any optional Quality Gate sandbox configuration is separate from OpenCode native tool permissions. OpenCode applies its usual precedence rules for identically named commands and skills.

After installation, run `/hx-security-status`. Do not start a protected workflow if the plugin is not active. In OpenCode, run `/connect`, select DeepSeek, then use `/models` to verify `deepseek/deepseek-v4-pro` and `deepseek/deepseek-flash`.

**Windows:** the default `ask-host` mode runs approved shell commands with the current operating-system user's permissions. The `sandbox-required` Bubblewrap mode is available on Linux/WSL with `bwrap` installed and should be validated on the target machine.

## Standard workflow

```text
/hx-plan Implement JWT authentication and add negative tests
```

Architect creates `.hx/plan.md`, registers an immutable plan version in Git-local storage, and reports its task ID and checksum.

```text
/hx-approve
```

Orchestrator calls **`hx_approve_plan`**, which must trigger the standard OpenCode approval prompt containing the plan name, version, and SHA-256. Choose **Allow once** only after reviewing the plan. Rejecting the prompt does not begin implementation. Plan approval is a separate workflow checkpoint and does not rely on shell command permissions.

After approval, HX creates a separate Git worktree. A local installation copies HX files missing from Git into that worktree; a global installation copies **only `.hx/plan.md`**, while the agents and Guard remain global. Developer and Test Engineer implement the task. Running Quality Gates calls **`hx_run_checks`** and requests explicit approval of the command list, working directories, and manifest. Two independent agents submit their reviews through **`hx_submit_review`**. Completion verifies that the checks and both reviews refer to the same workspace revision.

Other commands:

```text
/hx-status
/hx-tests
/hx-review
/hx-fix
/hx-resume
```

**Important:** `/hx-approve` and `/hx-tests` do not use Markdown `!` shell expansions. Those expansions would run outside the ordinary OpenCode tool-permission workflow. These actions use dedicated plugin tools instead.

## All 14 commands

| Command | Purpose |
|---|---|
| `/hx-plan` | Create and register a draft plan |
| `/hx-approve` | Request approval for an exact plan version |
| `/hx-status` | Show task state and workspace revision |
| `/hx-resume` | Continue from persisted task state |
| `/hx-tests` | Preview and approve Quality Gates |
| `/hx-review` | Run independent code and security reviews |
| `/hx-audit` | Run a deeper security assessment |
| `/hx-fix` | Address review findings and repeat checks |
| `/hx-diff` | Summarize Git changes |
| `/hx-pr` | Prepare a local pull-request draft |
| `/hx-land` | Safely commit and merge a completed HX worktree, or prepare a PR draft |
| `/hx-cost` | Record approximate token usage manually |
| `/hx-security-status` | Show HX workflow plugin status and native permission mode |
| `/hx-security-log` | Inspect sanitized HX tool activity (not user permissions) |

## Task persistence

- The Git common directory, `$(git rev-parse --git-common-dir)/hx/`, holds `state.json`, versioned plans, reports, the state lock, and the internal attestation key.
- **Task IDs are unique and immutable**, including for non-ASCII task names. Plans with the same title can be versioned; individual worktrees are bound to their own task IDs.
- `state.json` is written atomically, and CLI state transitions use an interprocess lock.
- Workspace revisions include `HEAD`, the Git index, and project-file contents. In global mode, the installed HX runtime, plugin, agent instructions, and global configuration are also hashed. Caches and transient data are excluded.
- `.hx/` is reserved for the current working plan and temporary reports. The example plan is installed at `hx/templates/plan.example.md` globally or `.opencode/hx/templates/plan.example.md` locally.

If you have several registered tasks in one checkout, select the intended task by ID or work in the corresponding worktree. Do not register a new plan inside another task's active worktree.

## Native permissions and retained workflow checkpoints

HX v5.8.0 delegates ordinary tool permissions to OpenCode; it does not force approval for each Git/shell command or block edits to `.opencode/hx/`. The plugin directory name `hx-command-guard` is retained for backward-compatible discovery, but it no longer installs permission or shell hooks. Use the normal **Allow once / Allow always / Deny** choices in OpenCode.

Two custom workflow actions remain: `hx_approve` requests specific approval of a plan digest before implementation, while `hx_checks` authorizes the exact Quality Gate manifest. You may save an **Allow always** decision for the same gate manifest; a changed manifest requires another permission decision. These are workflow checkpoints, not overrides of OpenCode's shell rules.

For a Java/Maven project, the Orchestrator may create `.opencode/hx/quality-gates.json` in the task worktree using native edit permissions. The old HX `tool.use edit:.opencode/hx/** deny` policy is removed by `--replace-hx` migration; user-defined or organization-wide deny rules are not forcibly removed. See [SECURITY.md](SECURITY.md).

## Quality Gates and sandbox

`/hx-tests` builds a SHA-256 manifest containing gate names, argument vectors, absolute working directories, executable identities, configuration, and the workspace revision. Changes to any of these inputs before execution invalidate the approval. Missing gates result in `UNVERIFIED`, **not** `PASS`.

In the default `ask-host` mode, OpenCode authorizes **the complete manifest of parent commands as a group**; child processes still run with the operating-system user's privileges. HX does not separately approve each process spawned by Maven, Gradle, npm, or similar tools. `sandbox-required` requires Bubblewrap and fails closed when it is unavailable. Even a sandbox cannot protect secrets stored inside the workspace made accessible to the build. See [SECURITY.md](SECURITY.md).

## Independent review reports

`review-schema.json` is validated with JSON Schema Draft 2020-12 plus domain invariants. An `APPROVED` report can have `PARTIAL` coverage with explicitly listed limitations for the inspected scope, but **formal completion requires `APPROVED + COMPLETE`** from both agents; unresolved MEDIUM, HIGH, or CRITICAL findings prohibit approval. `hx_submit_review` records the agent, session, message, task, and revision, then authenticates the payload using a local HMAC key. This **records which agent-bound plugin tool submitted the verdict**; it is not proof of review quality or protection against someone with access to the same operating-system account and Git storage.

## Upgrading or switching installation modes

1. Back up `.hx/`, your Git common directory's `hx/` folder, and existing OpenCode configuration. The included `install.py` does **not delete** user plans or state.
2. To keep local mode, run `python install.py local --target <git-project> --replace-hx`. For global mode, run `python install.py global` with your chosen Python interpreter.
3. When switching from local to global mode, **do not immediately delete `.opencode/`**. Validate the global installation first, then remove only HX-owned files from the repository, preserving custom agents and Quality Gates. Running both modes is supported.
4. Restart OpenCode and check `/hx-security-status` and `/hx-status` in a test repository. Plans and state in the Git common directory do not need migration.
5. HX commands use the plugin tools `hx_manage`, `hx_git_inspect`, `hx_guard_info`, `hx_approve_plan`, `hx_run_checks`, and `hx_submit_review`, rather than relative `python3 .opencode/hx/cli.py` calls.

## Tests

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
node --test tests/*.mjs
```

Unit tests do not replace validation against your actual OpenCode V2 installation. Use **a separate, empty Git repository without secrets**: create a plan, reject its approval, retry with approval, create a worktree, run a harmless Quality Gate, submit both independent reviews, then modify code after the checks and verify that task completion is rejected.

## Troubleshooting

- **Plugin unavailable:** inspect `/hx-security-status` and OpenCode startup logs. Do not invoke approval directly through a shell.
- **Approval rejected:** compare the task ID, version, and SHA-256 with the registered `.hx/plan.md`. A modified plan must be registered again.
- **Gate manifest changed:** rerun `/hx-tests` after changing files; do not reuse an old checksum.
- **Bubblewrap missing:** choose `ask-host` only if you accept execution on the host; otherwise keep `sandbox-required`.
- **Python cannot import `jsonschema`:** install dependencies from `requirements.txt` into the interpreter used by HX.
- **Worktree contains HX files:** inspect tracked files and `git status --short`. Untracked support files are excluded through Git `info/exclude`.
- **No API cost data:** HX records only manually supplied token counts; it does not know your actual DeepSeek API charges.

More information: [SETUP.md](SETUP.md), [SECURITY.md](SECURITY.md), [RELEASE_NOTES.md](RELEASE_NOTES.md), and [Internal architecture](.opencode/hx/README.md).

## Everyday development with native Plan and Build

Use OpenCode's built-in **Plan** and **Build** agents for everyday work. No HX shortcut agent or command is required.

1. Select the built-in **Plan** agent and discuss the change in Russian.
2. Approve the plan in the current session.
3. Switch to the built-in **Build** agent (using the agent selector/Tab) and ask it to implement the approved plan.

New sessions use **Build** by default when HX's example configuration is installed. Built-in Plan/Build do not register a versioned HX plan, create an HX worktree, or require dual review attestations. **Native OpenCode permissions govern shell, Git, PowerShell, cmd, editing, and MCP tools; HX does not override them.** For auditable work, run `/hx-plan` followed by `/hx-approve`.

### Russian conversation policy

The installer registers `hx/instructions/communication.md` as an OpenCode `instructions` entry, using an **absolute path globally** and a **project-relative path locally**. This is loaded for both native `Plan`/`Build` and HX agents. Conversations, progress, plans and review explanations are in **Russian** by default. Code comments, docstrings, repository documentation and identifiers stay in **English** unless explicitly requested otherwise. Existing `AGENTS.md` and other user instructions are not overwritten. After installing, restart OpenCode to reload the instruction file.

### Git references in standalone review

`/hx-review HEAD`, `/hx-review HEAD~1`, `/hx-review <sha>`, and `/hx-review <sha>~1` are supported. `hx_git_inspect(action: "commit")` exposes `parents` for correct single-commit ranges, including when HEAD points elsewhere. HX resolves symbolic Git references to immutable full commit SHA values before delegation and signed report persistence. Arbitrary revision expressions are not accepted. The plugin launches Git and Python child processes with Windows console windows hidden.

### Native tool permissions for every agent

All seven HX agents now inherit **OpenCode's normal tool permission rules**, including shell, read, edit, external directories, Code Mode and MCP. A saved **Allow always** choice is honored by OpenCode; HX does not turn it back into `ASK`. The Reviewer's read-only responsibility remains an instruction rather than a tool-enforced ban. To enforce stronger boundaries on particular projects, add your own OpenCode permissions or use isolated worktrees and OS-level sandboxes.

**Upgrade migration:** use `--replace-hx` to remove HX-owned legacy `permissions` and `policies` from a previously installed HX configuration. This includes the former hard deny on `.opencode/hx/**` that prevented creation of `quality-gates.json`. Custom rules with other patterns are preserved; a byte-identical rule cannot be reliably distinguished from a bundled legacy rule. Backups are created before updates. Read [SECURITY.md](SECURITY.md) before relying on permissions for sensitive repositories.

## Background Quality Gates (v5.8.0)

On Windows, background workers prefer `pyw.exe`/`pythonw.exe` and otherwise use `windowsHide: true` without creating a detached console. Maven/CMD subprocesses run with `CREATE_NO_WINDOW`. This prevents an HX-owned console from being intentionally created; verify on the target Windows installation. If the interpreter is not available in GUI form, the non-detached fallback may have different lifetime characteristics when the OpenCode host exits.

Quality Gates run in a detached Python worker rather than blocking the OpenCode server with a synchronous long-running child process. `hx_run_checks` previews and authorizes the manifest, then immediately returns `STARTED` and `job_id`; it does not claim `PASS`. The separate `hx_checks_status` tool reads persisted state from the repository's Git common directory (`hx/check-jobs/`) without waiting for Maven to complete. A background worker records `PASS`, `FAIL`, or `ERROR` and updates the formal HX task once the build finishes.

If the OpenCode server restarts, **do not repeatedly start new builds**. Reopen the session and query `hx_checks_status` using the previous worktree as `cwd`; poll until a terminal status is reported. When running from Windows, ensure the OpenCode server process has Maven and `JAVA_HOME` in its environment. Maven Wrapper and Maven commands are invoked through `cmd.exe /d /c` when autodetected on Windows.

A job whose state stays RUNNING/QUEUED past the recovery window is reported as `UNVERIFIED`, not `PASS`. Manual review of its `.log` file and worktree is required before retrying. Build commands run with the permissions of the user who approved the manifest; HX does not provide OS sandboxing in `ask-host` mode.

## Landing completed HX tasks — `/hx-land` (v5.8.0)

`/hx-land` runs **only after a task is COMPLETED**. Open the approved worktree and run `/hx-land` to preview the exact source files to be committed. Landing does not run automatically on `complete`. The Orchestrator asks for explicit consent, and `hx_land` uses the native OpenCode `hx_land` permission for each mutation.

1. `hx_land({action: "preview", cwd: "<worktree>"})` — read-only, shows the target branch, source files, content digest, and manifest digest. The original checkout must be clean and at the approved base commit.
2. `hx_land({action: "commit", cwd: "<worktree>", manifest_sha256: "<preview digest>"})` — creates the source commit, stages only eligible project files (not HX internals), and leaves the original checkout untouched.
3. Re-preview to get the separate MERGE manifest: `hx_land({action: "preview", cwd: "<worktree>"})`.
4. Choose either `action: "merge"` with the MERGE digest for local `git merge --no-ff --no-edit`, or `action: "pr"` for a **local PR draft only**. Both require native approval. A remote push or PR is never executed by HX.
5. Optional: switch OpenCode to the original checkout and call `hx_land({action: "cleanup", cwd: "<original>"})` after a successful merge. This never uses `--force` or deletes branches.

If the original target branch moved after HX plan approval, HX blocks automatic merging. Use `strategy: "pr"` in the initial preview and commit to prepare a local PR draft; pushing and opening a remote PR remain user-controlled. If the worktree changed after approved tests/reviews, HX blocks committing. Commit hooks are not disabled. If a post-commit hook changes source, HX refuses to merge without manual resolution.

**Older completed tasks:** v5.7.3 and earlier do not contain the portable source-content snapshot. If an HX runtime update changed the historical workspace revision, HX cannot prove the sources still match the original approvals and refuses normal landing. After reviewing all source diffs and expressly accepting that uncertainty, opt into `legacy_override: true` for a `LEGACY_MANUAL` commit, which prompts separately under `hx_land_legacy`. Do not mistake LEGACY_MANUAL for verified evidence.
