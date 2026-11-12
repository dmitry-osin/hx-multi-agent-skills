---
name: hx-kotlin
description: Kotlin engineering rules including coroutines and IntelliJ Platform
---

## When to use
Use for Kotlin source, coroutine flows, JVM services and IntelliJ Platform plugins.

## Rules
- Match existing Kotlin/JVM/IntelliJ SDK versions; do not rely on undocumented platform APIs.
- Favor immutable data, sealed hierarchies where justified, expressions with low branching complexity and explicit nullability.
- Keep coroutine scope and lifecycle ownership clear; never block UI/EDT; test cancellation, dispatchers and failures.
- In IntelliJ plugins respect write actions, dumb mode, disposables, project trust, threading and indexing.
- Avoid `!!`, global mutable state and long-lived cached PSI without lifecycle control.
- Comments in English; include focused Kotlin/JUnit regression tests and Gradle validation.
