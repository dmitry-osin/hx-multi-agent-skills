---
name: hx-sql
description: SQL schema, migrations, query safety and data integrity
---

## When to use
Use for SQL queries, schema migrations, repositories, PostgreSQL and database performance.

## Rules
- Match database dialect, schema owner and migration tool (Flyway/Liquibase/etc.).
- Always use bound parameters for external data; identify transaction isolation, concurrency and deadlock risks.
- Design idempotent migrations where reasonable; define rollback/forward-fix and compatibility with rolling deployments.
- Review indexes using query access patterns and real EXPLAIN plans when available, not invented benchmark numbers.
- Preserve constraints, foreign keys, null semantics, decimal precision and money representation.
- Test migrations against representative schemas and verify both backward and forward compatibility when required.
- Comments in SQL and code must be in English; avoid gratuitous ORM complexity.
