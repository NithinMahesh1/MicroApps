# Installation

This guide goes beyond the README's Quick Start. It documents exactly what the
installer scripts copy, where they put things, and how to remove the install
when you're done. For the one-liner version, see [README.md](../README.md#quick-start).

## Prerequisites

- **Python 3.11 or later.** ClaudePanes uses `tomllib` from the standard
  library, which was added in 3.11. The module-level docstring at
  `claude_panes.py:8` declares "Single-file, Python 3.11+, standard library
  only", and both installers gate on this:
  - `install.ps1:45` rejects anything older than 3.11.
  - `install.sh:54` runs `python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'`.
  There is no `pyproject.toml` — the script is intentionally not packaged.
- **At least one supported terminal multiplexer** on `PATH`:
  - Windows Terminal (`wt.exe`)
  - WezTerm (`wezterm cli`)
  - tmux
  - Zellij

  ClaudePanes only drives these; it does not install them. Run
  `claude-panes detect` after install to confirm the host has at least one.

- **No third-party Python packages.** Do not create a virtualenv for
  ClaudePanes — it is a single stdlib-only script.

## Recommended install (Windows)

The `install.ps1` script in the repo root is conservative: it copies files but
never edits your `PATH` or shell profile.

What it does, step by step (cross-referenced to the script):

1. **Verifies Python 3.11+** by parsing `python --version`
   (`install.ps1:27-50`).
2. **Locates `claude_panes.py`** next to the installer
   (`install.ps1:54-59`).
3. **Creates the install directory** if missing. Default:
   `%USERPROFILE%\.local\bin` (`install.ps1:22`, `install.ps1:63-66`).
   Override with `-InstallPath`.
4. **Copies `claude_panes.py`** into that directory
   (`install.ps1:70-74`).
5. **Writes a `claude-panes.cmd` shim** alongside it
   (`install.ps1:79-84`). The wrapper is two lines:

   ```bat
   @echo off
   python "%~dp0claude_panes.py" %*
   ```

   `%~dp0` is the directory of the `.cmd` file, so the wrapper finds its
   sibling `.py` regardless of the caller's working directory.
6. **Checks whether the install directory is on `PATH`**
   (`install.ps1:88-100`). If not, it prints — but does not run — the
   `[Environment]::SetEnvironmentVariable(...)` command for you to apply
   yourself. The installer never mutates user environment.
7. **Creates `%USERPROFILE%\.config\claude-panes\layouts\`** for your TOML
   layouts (`install.ps1:104-110`).

Run it from a clone of the repo:

```powershell
.\install.ps1
```

Or with a custom location:

```powershell
.\install.ps1 -InstallPath "C:\Tools\bin"
```

Open a new terminal (so any PATH change applies) and verify:

```powershell
claude-panes version
```

## Recommended install (macOS/Linux)

`install.sh` mirrors the PowerShell installer. Like its sibling, it is
conservative and never edits rc files.

What it does (cross-referenced to the script):

1. **Verifies Python 3.11+** via `python3 -c 'import sys; ...'`
   (`install.sh:49-58`).
2. **Locates `claude_panes.py`** next to the installer
   (`install.sh:64-70`).
3. **Creates the install directory** if missing. Default:
   `$HOME/.local/bin` (`install.sh:22`, `install.sh:74-77`).
   Override with `-p <path>` or `INSTALL_PATH=<path>`.
4. **Copies `claude_panes.py`** into that directory
   (`install.sh:81-85`).
5. **Writes a `claude-panes` bash wrapper** alongside it and `chmod 755`s it
   (`install.sh:89-94`). The wrapper is:

   ```bash
   #!/usr/bin/env bash
   exec python3 "$(dirname "$0")/claude_panes.py" "$@"
   ```

6. **Checks `PATH`** (`install.sh:98-105`). If the install dir is missing, it
   detects your shell (`SHELL`) and prints the matching `export PATH=...`
   line for `.bashrc`, `.zshrc`, or `config.fish` — you copy it yourself.
7. **Creates `$HOME/.config/claude-panes/layouts/`**
   (`install.sh:135-141`).

Run it:

```bash
bash install.sh
```

Or with a custom path:

```bash
./install.sh -p /opt/bin
```

Open a new shell (or `source` your rc file) and verify:

```bash
claude-panes version
```

## Manual install (no installer)

For local hacking or testing a branch, you can skip the installer entirely.
Clone the repo and invoke the script in place:

```bash
git clone <repo-url>
cd ClaudePanes
python claude_panes.py detect
python claude_panes.py validate examples/solo-claude.toml
python claude_panes.py start  examples/solo-claude.toml --dry-run
```

No copy, no wrapper, no PATH change. This is the recommended workflow when
contributing to the project.

## pipx

Not supported. A pipx-installable distribution is tracked under Phase 4 in
[PROGRESS.md](../PROGRESS.md) ("Distribution: pipx-installable, single-file
script also works standalone") and is not yet implemented. Use the install
scripts above.

## WSL note (Windows + tmux)

If you want to drive **tmux** from a Windows host, install and run
ClaudePanes inside WSL — not on the Windows side. Per
[ADR-013](design-decisions.md) in `docs/design-decisions.md`, ClaudePanes
does not auto-wrap tmux calls with `wsl.exe`; tmux is a POSIX tool with no
native Windows port. From a native Windows install, `claude-panes detect`
will correctly report tmux as unavailable.

To run inside WSL, open your WSL distro and run `bash install.sh` from the
cloned repo. The Windows Terminal, WezTerm, and Zellij adapters do not need
this — only tmux.

## Uninstalling

The installers do not record what they did, but they only write three things.
Remove them by hand.

**Windows** (PowerShell):

```powershell
$dir = "$env:USERPROFILE\.local\bin"
Remove-Item "$dir\claude_panes.py", "$dir\claude-panes.cmd"
```

If you added the install directory to your user `PATH`, open
*Settings → System → About → Advanced system settings → Environment
Variables* and remove the entry — or run:

```powershell
$old = [Environment]::GetEnvironmentVariable('Path','User')
$new = ($old -split ';' | Where-Object { $_ -ne "$env:USERPROFILE\.local\bin" }) -join ';'
[Environment]::SetEnvironmentVariable('Path', $new, 'User')
```

Optionally remove your layouts directory:

```powershell
Remove-Item -Recurse "$env:USERPROFILE\.config\claude-panes"
```

**macOS/Linux:**

```bash
rm "$HOME/.local/bin/claude_panes.py" "$HOME/.local/bin/claude-panes"
```

Then delete the `export PATH=...` line you added to your shell rc file, and
optionally `rm -rf "$HOME/.config/claude-panes"`.

## Verifying your install

Two commands confirm the install works:

```bash
claude-panes version
```

Prints `claude-panes <VERSION>` and the Python interpreter version
(`claude_panes.py:854-857`).

```bash
claude-panes detect
```

Lists each supported terminal and the path where it was resolved (or
`not found`). At least one entry must resolve for `start` to do anything
useful; otherwise `detect` exits non-zero with "no supported terminal
installed".

For a full end-to-end smoke test without launching anything:

```bash
claude-panes validate examples/solo-claude.toml
claude-panes start    examples/solo-claude.toml --dry-run
```

`--dry-run` prints the terminal invocation ClaudePanes would have executed,
without actually spawning a process.
