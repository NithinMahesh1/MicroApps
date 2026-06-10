---
name: Bug Report
about: Report a bug in ClaudePanes
title: "[BUG] "
labels: bug
assignees: ''
---

## Describe the bug

A clear, 1-2 line description of what happens versus what you expected to happen.

## Reproduction

Steps to reproduce the behavior:

1. Save the following layout as `repro.toml`:

   ```toml
   [layout]
   name = "repro"

   [[panes]]
   id = "main"
   command = "claude"
   ```

2. Run `claude-panes start repro.toml`
3. Observe the issue

## Expected behavior

What you expected to happen instead.

## Output of `claude-panes detect` and `claude-panes version`

Paste the full output of both commands here so we can see the detected terminal and Python version.

```
$ claude-panes detect
...

$ claude-panes version
...
```

## OS

Windows / macOS / Linux, plus version (e.g. Windows 11 23H2, macOS 14.4, Ubuntu 22.04).

## Terminal multiplexer

Which adapter and version (e.g. Windows Terminal 1.19, WezTerm 20240203, tmux 3.4, Zellij 0.40).

## Did you try `claude-panes start <file> --dry-run`?

Yes / No. If yes, paste the dry-run output - it helps us isolate adapter issues from launch issues.

## Additional context

Anything else relevant: config snippets, screenshots, logs, related issues.
