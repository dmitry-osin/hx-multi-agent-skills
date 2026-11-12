# HX v5.8.0 — Verified Landing

Adds source-bound previews, dedicated commit/merge permissions, target-advance refusal, protected HX files and explicit optional cleanup.

---

# Historical: HX v5.7.3 — Formal Review Routing Fix

- Corrected false `FILE_UNAVAILABLE` errors caused by auditing new worktree files against a parent Git revision.
- Added explicit FORMAL/STANDALONE tool modes, meaningful errors for 64-digit workspace fingerprints, and mode guidance from `hx_review_contract`.
- Gave both independent reviewer agents a 48-step submission budget.
- Preserved permission behavior and signed provenance.

---

# Historical: HX v5.7.3 — Security and Reliability Audit Resolution Matrix

**Author:** Dmitry Osin  
**Date:** November 12, 2026  
**Scope:** Previously identified security and reliability findings in the HX workflow.  
**Verification performed:** Static inspection, Python unit/regression tests, Node.js tests, and an emulation of the OpenCode V2 server-plugin API. Live OpenCode client/UI, DeepSeek API, target operating system/WSL, and Bubblewrap execution are outside the automated test coverage.

| ID | Resolution | Verification / limitation |
|---|---|---|
| P0-01 | Removed shell preambles from the 13 pre-landing slash commands. Plan approval now uses `hx_approve_plan`. | Tests reject command preambles and emulate a denied permission request. Does not constrain actions initiated directly by the operating-system user. |
| P0-02 | Added manifest-locked Quality Gates and explicit `hx_checks` authorization; `sandbox-required` fails closed. | Negative manifest-mismatch tests, mocked permission rejection, and post-run revision checks. Child processes are not individually intercepted in `ask-host` mode. |
| P0-03 | Workspace revision hashing covers Git `HEAD`, index, and file contents, including relevant ignored HX configuration. | Tests cover commits, configuration changes, deleted files, and stale reviews. |
| P0-04 | Previous HX enforced `ASK` for unknown MCP tools. This restriction is deliberately retired; native OpenCode permissions now apply. | Tests verify the HX permission hook is not installed. |
| P1-01 | Added Unicode-compatible task slugs with immutable UUID suffixes. | Tasks with different non-ASCII titles obtain distinct IDs. |
| P1-02 | Added `by_checkout`, explicit `--task-id` selection, `state.lock`, and atomic state writes. | Tests exercise concurrent CLI state mutations and token records. |
| P1-03 | Added safe HX file copy into worktrees and Git exclusions for untracked support files. | Worktree tests cover existing-file conflicts and directory state. |
| P1-04 | Restricted Bubblewrap mounts; isolated `HOME` and environment; disabled network by default. | Static checks; real Bubblewrap validation on the target Linux/WSL system is still needed. |
| P1-05 | Added JSON Schema Draft 2020-12 and domain validation for nonempty fields, unique IDs, and real file locations. | Negative tests for signed reviews. |
| P1-06 | Bound Quality Gates to SHA-256 manifests of argv, working directory, executable, configuration, and workspace revision; checked before and after execution. | Manifest tampering tests. |
| P1-07 | Added `hx_submit_review` for `reviewer` and `security-auditor`, session metadata, and HMAC. | Tool-execution simulation. HMAC cannot prevent tampering by an attacker who controls the same operating-system account. |
| P2-01 | Removed the unnecessary external npm dependency instead of introducing a pin or lockfile. | `package.json` has no dependencies; the plugin exports the V2 object. |
| P2-02 | Switched to `git status --porcelain=v1 -z` handling. | Tests for renames involving whitespace and Unicode. |
| P2-03 | Added discovery of multiple Gradle/Maven/npm roots and explicit SQL gate examples. No gates means `UNVERIFIED`. | Unit tests; SQL gates must still be tailored to the project. |
| P2-04 | Added a root README and updated installation, security, and internal architecture guides. | Documentation presence and consistency checks. |

## Remaining risks and trust boundaries

1. In `ask-host` mode, users approve the complete Quality Gate list, **not** each process spawned by a gate. Without operating-system isolation, a child process started by approved Gradle, npm, Python, or Java code could invoke `rm` or other destructive operations.
2. The internal HMAC key is accessible to the same user who runs OpenCode. Its role is to detect accidental report changes and to associate reports with an HX plugin submission, **not** to withstand compromise of that user account.
3. Bubblewrap restricts host visibility, but the mounted project remains accessible to the build, including any `.env` files or other secrets present. Do not run untrusted builds in checkouts containing secrets.
4. The workspace checksum covers relevant project files, but **not** external databases, unobserved background processes, all host state, or the contents of every ignored file outside HX configuration.
5. A live OpenCode V2 client/UI integration test is needed to verify plugin registration and actual permission prompts. Simulating the plugin API does not replace that check.

## Recommended on-machine acceptance checks

- Open OpenCode V2 in a disposable Git repository without secrets and verify `/hx-security-status`.
- Run `/hx-plan`, then `/hx-approve`. Rejecting the prompt must leave the plan in `DRAFT`; approving it must move the plan to `APPROVED`.
- Verify the worktree does not contain unintended untracked HX bundle files. `/hx-tests` must display the exact gate argv and checksum.
- Run a harmless test gate, then modify a source file and verify that task completion is rejected.
- Verify that `reviewer` and `security-auditor` can call `hx_submit_review`, while `orchestrator` cannot impersonate either reviewer.
- Verify that `git push`, destructive shell commands, and unknown MCP tools request permission on every attempt. **Use harmless stand-ins or mocks; do not execute real destructive commands for testing.**

## v5.5.0 follow-up fixes

- Independent commit/range reviews no longer depend on plan registration, approval, or worktrees.
- Read-only Git inspection is exposed through a bounded HX plugin tool rather than unavailable shell tools.
- Approval preflight runs before prompting and CLI failures include the underlying error.
- Standalone results are stored under Git-common HX state; complete `APPROVED` results require validated independent agent submissions.

## v5.6.0 follow-up: review report reliability

- Unified reviewer prompts with the installed `review-schema.json` through `hx_review_contract`.
- Added a non-persistent `hx_validate_review` tool and source-bound preflight on submission.
- Required literal `anchor` evidence for each finding, with unambiguous line resolution or exact line verification; invented in-range lines are rejected.
- Separated `coverage` from `verdict`, while requiring complete coverage before formal task completion.
- Added machine-readable, path-specific validation errors and regression tests for malformed reports and missing evidence.

## Explicit SHA ancestry support (previous improvement)

- Fixed `hx_git_inspect` refusing `<SHA>~1` and `<SHA>^N` while accepting the equivalent HEAD expressions.
- A `commit` inspection now yields `parents` for its resolved SHA so a review agent does not accidentally use `HEAD~1` from another branch or newer commit.
- The allowed reference grammar still forbids stacked suffixes, option strings, revision ranges passed as a single commit ref, reflog selectors, and path expressions.

## Updated permission architecture (current release)

The former HX-specific tool denials and repeated shell prompts have been removed to restore OpenCode native permission choices. Legacy policy migration is performed by `install.py --replace-hx`. Dedicated `hx_approve` and `hx_checks` actions remain as formal workflow checkpoints. See [SECURITY.md](SECURITY.md).
