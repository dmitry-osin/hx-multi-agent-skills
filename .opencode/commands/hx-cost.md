---
description: "Show recorded HX token estimates without an HX plan"
agent: orchestrator
---

Use `hx_manage` with `action: "cost"`. This is available without an active HX task and returns NO DATA rather than failing when no records exist. HX estimates include only manually recorded tokens, never automatic DeepSeek API billing. For real OpenCode historical billing suggest the local `opencode stats --cost` CLI to the user; do not invent billing numbers. Scope: $ARGUMENTS
