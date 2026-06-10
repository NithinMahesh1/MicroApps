# Related Claude Code Features

ClaudePanes is not the only tool in this space. Anthropic has recently shipped capabilities that overlap with parts of what ClaudePanes does. This doc captures what's worth knowing so you can pick the right tool — or combine them.

## `claude agents` — background sessions

Claude Code recently added a built-in way to run Claude sessions in the background. As described by Dakota (Anthropic):

> Agents here keep running even if you close this terminal — hand off a task and check back later.
>
> Try: paste a link, or "review PR #123 for bugs" · "fix the failing test" · "babysit my PR until CI passes"

What this gives you:

- Sessions persist after you close the terminal.
- One dispatch screen for all running sessions.
- Designed for hand-off-and-check-back-later work — long PR reviews, CI babysitting, fix-then-tell-me tasks.

### How to invoke

The CLI moves fast and surfaces change between releases. Confirm syntax with `claude --help` on your installed version before scripting around it. The shape commonly cited is along the lines of:

```
claude agents              # open the dispatch / background-sessions view
claude --bg "<prompt>"     # start a session that runs in the background
```

If your installed Claude Code does not recognize a command, treat the docs as ahead-of-binary and check again after the next update.

## Where ClaudePanes still fits

ClaudePanes and `claude agents` solve overlapping problems differently. They are complements, not competitors.

| Need | Better tool |
|---|---|
| Fire-and-forget a task; check back when it finishes | `claude agents` / `--bg` |
| Watch N live Claude sessions side-by-side in real terminal panes | ClaudePanes |
| Babysit a PR until CI passes while you do other work | `claude agents` |
| Pair-program with Claude while a second pane runs `watch git status` and a third runs the dev server | ClaudePanes |
| Per-pane WSL2 distro or sandbox profile | ClaudePanes |
| Session that survives a terminal close | `claude agents` |
| Reproducible team layout described in a TOML file checked into the repo | ClaudePanes |

A reasonable combined workflow:

- Long-running, async work → `claude --bg` / `claude agents`
- Active hands-on-keyboard work with side-by-side observation → a ClaudePanes layout
- One ClaudePanes pane can itself be `claude agents` (the dispatch TUI) while other panes are interactive sessions.

## Other related features

- **`claude -p "<prompt>"`** — headless, one-shot, exits when done. Useful in scripts. Orthogonal to layout work.
- **`/loop`** — repeat a prompt on an interval inside one session.
- **`/schedule`** — cron-style scheduled runs on Anthropic infrastructure (research preview at the time of writing).
- **Subagents via the Task tool** — intra-session delegation. Distinct from running multiple top-level Claude sessions in parallel; not a replacement for either ClaudePanes or `claude agents`.

## Verifying current behavior

Before scripting against any of the above:

```
claude --help
claude agents --help     # confirm subcommand exists
claude --bg --help       # confirm flag exists
```

Update this doc when the surface changes. Capture the date and the version of Claude Code you verified against.

## When to retire ClaudePanes

If Claude Code one day ships native side-by-side terminal-pane layouts with per-pane sandbox/distro selection, configurable via a checked-in file, ClaudePanes' niche disappears. Until then it occupies a real corner: visual, terminal-native, declarative, multi-terminal-host, and complementary to whatever Anthropic ships for background work.
