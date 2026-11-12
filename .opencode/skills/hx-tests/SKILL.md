---
name: hx-tests
description: Testing strategy and acceptance-verification practices
---

## When to use
Use for every change that needs verification, test generation, or diagnosis of failing tests.

## Rules
- Translate each approved acceptance criterion into positive, negative, boundary and regression cases.
- Separate unit, integration, contract and end-to-end tests. Avoid network, clock and randomness dependencies where feasible.
- Reuse project test style and tooling; do not weaken existing assertions to make tests pass.
- Record each executed command, exit code and substantive result. A missing tool or unrun test is UNVERIFIED, never PASS.
- Favor narrow fixtures and deterministic test doubles; preserve test readability and low branching complexity.
- Do not claim coverage metrics without actual instrumentation.
- Run HX quality gates in addition to agent-selected focused tests.
