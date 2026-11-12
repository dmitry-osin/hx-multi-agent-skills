---
name: hx-java
description: Java engineering conventions for approved application changes
---

## When to use
Use for Java source changes, Spring services, Java libraries, and Maven/Gradle projects.

## Rules
- Match the existing JDK baseline, style, build system, package boundaries, and public APIs.
- Prefer explicit types for public contracts, small methods and cohesive classes; minimize cognitive and cyclomatic complexity.
- Respect nullability, immutability, checked/unchecked exceptions, exception logging, and resource closing with try-with-resources.
- For Spring: retain transaction boundaries, avoid lazy-loading N+1 issues, validate inputs and secure endpoints.
- Write all code comments in English. Avoid comments restating simple code.
- Add JUnit 5 tests, integration tests where necessary, and run existing Maven/Gradle tasks.
- Avoid broad refactors without approval; record compatibility and migration effects.
