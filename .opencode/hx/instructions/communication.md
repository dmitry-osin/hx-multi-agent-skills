# HX Communication Rules

These rules apply to all available OpenCode agents, including native Plan and Build and the HX specialist agents.

- Communicate with the user **in Russian** for planning, explanations, clarifying questions, progress reports, reviews, permission context and final results unless the user explicitly requests another language.
- Keep code comments and docstrings **in English**. Use descriptive English identifiers, conventional API naming, and low cyclomatic and cognitive complexity.
- Preserve file paths, CLI commands, symbols, diagnostics, error codes, stack traces, JSON keys and other technical literals; do not translate them in a way that breaks copy/paste usage.
- Technical artifacts and repository documentation should be in English unless the user explicitly requests otherwise. Do not translate existing source files just to comply with the conversation language.
- Report what was actually changed or tested. Separate confirmed results from unverified assumptions; do not claim passing tests or completed checks without evidence.
- Be concise and clear. For potentially destructive actions, explain the impact in Russian and rely on the actual OpenCode permission request; ordinary conversation approval never replaces a command/tool permission prompt.
- When planning and implementation are distinct steps, ask the user to approve the plan before editing. In the full HX workflow use `/hx-approve`; in native Plan → Build, the user's explicit acceptance in the current session suffices for ordinary edits.
