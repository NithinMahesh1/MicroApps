# ClaudePanes — How to Run It

A plain-language guide to running ClaudePanes. For the full specification see
[`docs/cli-spec.md`](docs/cli-spec.md) and [`docs/config-format.md`](docs/config-format.md).

## What this is

ClaudePanes is a single-file Python CLI (`claude_panes.py`) that reads a TOML
*layout* file and opens a terminal multiplexer — Windows Terminal, WezTerm,
tmux, or Zellij — with your panes pre-arranged, each pane running a command
(typically `claude`). Zero third-party dependencies; just Python 3.11+.

## Current status (2026-05-27)

- **Phase 1 complete:** code + 89 passing tests + CI. Two commits on `main`:
  `3ab2599` (MVP) and `434806e` (cross-platform + security/test hardening).
- **Security:** reviewed with `bandit` + a manual audit — no exploitable
  vulnerabilities (argv-list subprocess, no `shell=True`, correct KDL escaping).
- ⚠️ **Not yet confirmed by a real launch.** Everything is verified by unit
  tests and `--dry-run` only. Do the check below before relying on it.

## ⚠️ First: verify it actually works

Before relying on it (or building anything new), launch one for real and watch it:

```powershell
python claude_panes.py start examples/solo-claude.toml
```

Windows Terminal should open with the pane and the command should run. If it
doesn't, see [`docs/troubleshooting.md`](docs/troubleshooting.md). This is the
same blocking gate tracked at the top of [`PROGRESS.md`](PROGRESS.md).

## Run it from the repo (no install)

From the repo root (where you cloned ClaudePanes):

```powershell
python claude_panes.py detect                                    # which terminals are installed
python claude_panes.py version                                   # tool + python version
python claude_panes.py validate examples/solo-claude.toml        # check a layout is valid
python claude_panes.py start examples/solo-claude.toml --dry-run # PREVIEW the command (don't launch)
python claude_panes.py start examples/solo-claude.toml           # LAUNCH it
```

Useful flags on `start`:

| Flag | What it does |
|------|--------------|
| `--dry-run` | Print the command(s) instead of running them — best way to see what it *will* do. |
| `--terminal {wt,wezterm,tmux,zellij}` | Force a specific terminal (it must be installed). |
| `-v` / `--verbose` | Log which adapter + layout was chosen, to stderr. |
| `--config-dir DIR` | Use a different config root than `~/.config/claude-panes`. |

Exit codes: `0` ok · `1` unexpected · `2` config error · `3` no terminal found ·
`4` adapter execution error.

## Install it as a `claude-panes` command

```powershell
.\install.ps1
```

This:
- copies `claude_panes.py` + a `claude-panes.cmd` wrapper to `%USERPROFILE%\.local\bin`,
- creates your layouts folder at `~/.config/claude-panes/layouts/` (`~` = `%USERPROFILE%` on Windows),
- does **not** change PATH — it prints the exact command to add that folder to your user PATH.

Open a new terminal, then:

```powershell
claude-panes --help
claude-panes detect
claude-panes start solo-claude     # runs ~/.config/claude-panes/layouts/solo-claude.toml
```

Requires Python 3.11+. On macOS/Linux use `./install.sh` instead. Full details:
[`docs/installation.md`](docs/installation.md).

## Writing your own layout

Drop a `.toml` in `~/.config/claude-panes/layouts/` and run it by bare name
(`claude-panes start <name>`), or point at any path
(`claude-panes start ./my-layout.toml`).

Minimal example:

```toml
name = "my-work"

[[panes]]
cmd = "claude"

[[panes]]
cmd = "git status -sb"
split = "vertical"
size = 0.3
```

Full field reference: [`docs/config-format.md`](docs/config-format.md).
Eight ready-to-copy layouts live in [`examples/`](examples/).

## Security summary

- Commands run via explicit argv lists — never `shell=True`. Your `cmd` string
  is handed to your shell as a single opaque element (`cmd.exe /c` on Windows;
  `$SHELL -lc`, falling back to `/bin/sh -c`, on POSIX).
- The TOML author **is** the operator: you are configuring commands to run on
  your own machine. There is no untrusted-input boundary.
- `bandit` + manual audit (2026-05-22): no exploitable findings.
- Full notes: [`docs/security.md`](docs/security.md) and [`SECURITY.md`](SECURITY.md).

## Known limitations (deferred, non-blocking)

- **Zellij** ignores a pane's `working_dir` (no `cwd` emitted) and hardcodes the
  command shell to `bash`.
- `start --dry-run --terminal X` still requires X to be installed — you can't
  preview the command for a terminal you don't have.
- No example yet demonstrates `shell_prelude` (it joins to each pane cmd with ` && `).

## Cutting the v0.1.0 release

Once a real launch is confirmed **and** the repo is pushed to GitHub:

```powershell
git tag v0.1.0
git push --tags
```

This triggers [`.github/workflows/release.yml`](.github/workflows/release.yml),
which runs the test suite and publishes `claude_panes.py` + its `.sha256`
checksum to a GitHub Release.

## Where to look next

| File | What's in it |
|------|--------------|
| [`docs/installation.md`](docs/installation.md) | Detailed install steps + PATH setup |
| [`docs/cli-spec.md`](docs/cli-spec.md) | Every command, flag, and exit code |
| [`docs/config-format.md`](docs/config-format.md) | TOML layout schema |
| [`docs/terminal-adapters.md`](docs/terminal-adapters.md) | How each terminal is driven |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | When something doesn't launch |
| [`docs/faq.md`](docs/faq.md) | Common questions |
| [`PROGRESS.md`](PROGRESS.md) | Project status + the verify-it-works gate |
