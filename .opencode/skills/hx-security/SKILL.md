---
name: hx-security
description: Threat modeling and secure coding/audit of approved changes
---

## When to use
Use on every nontrivial change and always for auth, secrets, dependency management or untrusted input.

## Rules
- Identify entry points, trust boundaries, privileges, sensitive data and feasible misuse scenarios.
- Check authentication, authorization, credential handling, injections (SQL/OS/HTML), SSRF, file access and unsafe serialization as relevant.
- Review dependencies and logging for secrets/PII exposure. Avoid reading actual secrets unnecessarily.
- Distinguish observable evidence from assumptions; do not report generic issues without an affected code path.
- Rate CRITICAL/HIGH/MEDIUM/LOW/INFO and include real file/line/evidence and minimal remediation.
- Static review does not prove absence of security flaws; never claim dynamic exploit testing without running it.
- Findings requiring code changes return to Developer; auditor remains read-only.
