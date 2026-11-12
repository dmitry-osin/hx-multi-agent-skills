# HX v5.8.0 — Internal Architecture

`standalone.py`: independent SHA- and range-bound reviews with schema/provenance validation; no HX plan required.

`state.py`: Git-common task storage (`state.json`, `plans/`, `reports/`, `state.lock`, `attest.key`), unique task IDs, and worktree bindings. CLI operations use an interprocess lock.

`cli.py`: deterministic operations including `submit`, `status`, `verify`, `approve`, `attach`, `start`, `checks-preview`, `checks`, `review`, `cycle`, `complete`, `cost`, `diff`, `pr`, and `revision`; also provides `approve-preflight` and `standalone-review`.

`gates.py`: a manifest containing SHA-256 executable identities, absolute paths, source revision, and configuration hash. Inputs are revalidated before each gate. Does not use `shell=True`. Host execution follows the HX manifest-bound permission tool; Linux sandbox execution uses Bubblewrap. Missing gates never count as a pass.

`review-schema.json`: required fields, nonempty evidence, existing file locations, and JSON Schema Draft 2020-12 validation. Dependencies are documented in `requirements.txt`.

`plugins/hx-command-guard/`, relative to the OpenCode configuration root: `guard.js` (sanitized audit hashing), `workflow.js` (workflow and read-only Git inspection tools bound to the session), and `index.js` (registration and hooks). No npm runtime dependencies. Native OpenCode permissions govern MCP, shell, read and edit; no HX permission hook is installed.

The plan template is `templates/plan.example.md`. `.hx/` is reserved for project-generated artifacts and is not included in the source package. For additional guidance, consult the distribution’s top-level `README.md` and `SECURITY.md`.

## Runtime location

`runtime.py` finds the installed HX directory: `~/.config/opencode/hx` in global mode or `<repo>/.opencode/hx` in local mode. The plugin locates CLI files relative to its own installation path. Commands call `hx_manage` and `hx_guard_info` rather than invoking Python at a repository-relative location.

In either installation mode, task state and report-attestation keys live at `$(git rev-parse --git-common-dir)/hx`, while working plans remain under `<repo>/.hx/`. The globally installed HX bundle is not copied into Git worktrees.

## Native Plan integration

Built-in Plan and Build remain available for ordinary development without persisted HX plans. `hx/instructions/communication.md` is installed into the OpenCode `instructions` array in both installation modes and applies to native and HX agents.

`review_contract.py` is the single source for review JSON Schema validation, coverage semantics, and evidence anchoring. It reads `review-schema.json`, checks a literal source anchor at the reviewed commit/workspace revision, and resolves missing line numbers only for unique matches. `cli.py review-validate` receives a JSON report on stdin and returns non-persistent structured issues. The plugin publishes this contract through `hx_review_contract` and calls the preflight via `hx_validate_review` and `hx_submit_review` before persistence; formal and standalone paths both revalidate in Python.

Reviewer shell permission rule: agent YAML uses `shell: * -> ask`, and the Guard `permission.evaluate` hook enforces fresh `ask` for every `reviewer`/`security-auditor` shell operation, even after a saved OpenCode allow. The UI may still offer Allow always; this is not an OS sandbox.

Long-running Quality Gates use detached `checks_worker.py` jobs, monitored via `hx_checks_status`, not a synchronous OpenCode tool call.

## Review modes

`hx_review_contract` with the approved worktree `cwd` returns `review_mode=FORMAL`. The reviewer must omit `target/base` and pass `mode=FORMAL` for both validation and submission. Formal source anchors read the current worktree (including new untracked files). `mode=STANDALONE` is required to intentionally review a fixed commit while a formal task is active; a standalone range validates files at `target`, never `base`. A 64-digit HX workspace SHA-256 is not a Git SHA.

## Landing (v5.8.0)

`land.py` owns post-COMPLETED worktree-to-original-checkout landing. `can_complete()` stores `land_source_digest`, separate from the runtime-sensitive HX `workspace_revision`. A read-only preview produces a manifest hash, used for an explicitly permitted source commit. A second preview and explicit permission are required for merge. Optional `pr` and `cleanup` actions are separate. All Git invocations use argv arrays without shells; target tip and tree are verified before writing final landing state.
