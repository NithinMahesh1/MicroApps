# ClaudePanes

ClaudePanes — launch pre-configured terminal pane layouts for parallel Claude Code sessions.

## What it is

ClaudePanes is a zero-dependency, single-file Python launcher (Python 3.11+, stdlib only). It reads a TOML layout config and shells out to whichever terminal multiplexer is installed on your machine — Windows Terminal (`wt.exe`), WezTerm (`wezterm cli`), tmux, or Zellij — to open tabs with pre-split panes running pre-configured commands.

Its primary use case is launching parallel Claude Code sessions across multiple git worktrees on Windows 11, with each pane running inside WSL2 so `/sandbox` works.

## What it is NOT

- Not a terminal emulator.
- Not a terminal multiplexer.
- Not a PTY host.
- Not a GUI.
- Not a replacement for Windows Terminal, WezTerm, tmux, or Zellij — it drives them.

The terminal already installed on your machine does the pane mechanics. ClaudePanes only translates TOML into that terminal's CLI invocation.

## Why it exists

Three problems motivated this project:

1. **Multi-pane Claude Code workflow on Windows.** Spinning up several Claude Code sessions across worktrees by hand — opening tabs, splitting panes, `cd`-ing into the right directories, starting `claude` in each — is tedious and easy to get wrong. ClaudePanes makes a layout reproducible from a config file.
2. **`/sandbox` via WSL2.** Claude Code's `/sandbox` mode needs a Linux environment on Windows. Each pane needs to drop into WSL2 in the correct worktree path before launching Claude. ClaudePanes encodes that wrapping per-pane.
3. **Permission yes-fatigue is out of scope.** That is solved separately via Claude Code's own `settings.json` allowlist — see [docs/permission-allowlist.md](docs/permission-allowlist.md). ClaudePanes does not touch permissions.

## Requirements

- Python 3.11 or later (uses `tomllib` from stdlib).
- One of the following terminals installed and on PATH:
  - Windows Terminal (`wt.exe`)
  - WezTerm (`wezterm cli`)
  - tmux
  - Zellij
- For the `/sandbox` use case: WSL2 with a configured distro.

No third-party Python packages. No installer. Single-file script.

## Quick Start

Note: the `iwr | iex` / `curl | bash` one-liners become available once this repo is published to GitHub. Until then, clone the repo and run the installer locally.

### Install (Windows)
PowerShell:
    iwr -useb <RAW_URL>/install.ps1 | iex
or, from a local clone:
    .\install.ps1

### Install (macOS/Linux)
    curl -fsSL <RAW_URL>/install.sh | bash
or, from a local clone:
    bash install.sh

### Run
    claude-panes detect                            # see which terminals are available
    claude-panes validate examples/solo-claude.toml
    claude-panes start examples/solo-claude.toml   # add --dry-run to preview the command

## Status

Pre-MVP. Documentation phase. No code yet. See [PROGRESS.md](PROGRESS.md) for current state and next milestones.

## Documentation

- [docs/architecture.md](docs/architecture.md) — Component overview and execution flow.
- [docs/design-decisions.md](docs/design-decisions.md) — Why TOML, why stdlib-only, why a launcher (not a multiplexer).
- [docs/security.md](docs/security.md) — Command construction, shell safety, threat model.
- [docs/terminal-adapters.md](docs/terminal-adapters.md) — How each backend (`wt`, `wezterm`, `tmux`, `zellij`) is invoked.
- [docs/config-format.md](docs/config-format.md) — TOML schema reference.
- [docs/cli-spec.md](docs/cli-spec.md) — Subcommands, flags, exit codes.
- [docs/usage-examples.md](docs/usage-examples.md) — Worked examples for common workflows.
- [docs/permission-allowlist.md](docs/permission-allowlist.md) — Eliminating Claude Code yes-fatigue via `settings.json`.
- [PROGRESS.md](PROGRESS.md) — Roadmap and milestone tracking.

## License

License TBD.
