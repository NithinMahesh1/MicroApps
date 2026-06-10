---
name: Feature Request
about: Suggest a feature for ClaudePanes
title: "[FEATURE] "
labels: enhancement
assignees: ''
---

## What problem does this solve?

Describe the user-facing problem or workflow gap. Focus on the "why" before the "how".

## Proposed solution

Be specific. If this changes the TOML schema, show the proposed keys and example values. If this adds or changes a CLI flag, show the exact flag name, arguments, and an example invocation.

## Alternatives considered

What other approaches did you weigh? Why is the proposed one preferable?

## Would this affect

- [ ] Config schema (`claudepanes.toml`)
- [ ] CLI surface (flags, subcommands, exit codes)
- [ ] Adapter behavior (Windows Terminal, iTerm2, tmux, etc.)
- [ ] Documentation only

## Out-of-scope check

The following are explicitly out of scope per the project's ADRs (`docs/design-decisions.md`) and roadmap (`PROGRESS.md`). Please confirm your request does **not** fall into any of these:

- PTY hosting (ClaudePanes does not own or multiplex pseudo-terminals)
- TUI dashboard (no interactive in-terminal UI is planned)
- Background daemon or long-running service
- Input broadcasting (sending the same keystrokes to multiple panes)
- Running-state observation (inspecting what a pane is currently doing)

- [ ] I have confirmed my request does not rely on any of the above.

If it does, please open a discussion first so we can talk about scope before filing an issue.
