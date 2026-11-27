# Coding agent instructions for NEBIX

For coding agents that discover and load repository guidance, these instructions apply when modifying this project. Verify the current tool's guidance-discovery behavior instead of assuming every coding tool automatically reads `AGENTS.md`. These instructions are separate from NEBIX's user-facing runtime rules in `core/runtime_rules/`; never load this file as a runtime assistant prompt.

- Read the relevant source, configuration, prompt, and documentation files before changing code.
- Understand the existing NEBIX architecture and trace the real call path before implementing a change.
- Follow existing naming, imports, dependencies, formatting, and coding patterns.
- Reuse existing helpers, permission checks, task management, and UI components instead of duplicating them.
- Preserve working features, user data, and existing security, privacy, and permission boundaries.
- Avoid unnecessary dependencies, abstractions, boilerplate, duplicate files, and unrelated changes.
- Implement only the requested scope. Do not redesign the UI unless explicitly requested.
- Follow the existing project structure; do not impose an unrelated architecture.
- Test actual behavior with the smallest relevant existing or focused test. Distinguish tests run from code inspection and live desktop testing.
- Never claim a feature, build, or test works unless it was actually tested and passed. Do not fabricate results or hide failures.
- Report incomplete work, blockers, and unverified behavior accurately.
- Ask the user only when an essential ambiguity, missing authorization, or blocker prevents safe implementation; otherwise make a conservative assumption and proceed.
