# Troubleshooting

Common ClaudePanes failures, organized by what you see. Each entry follows the
**Symptom** -> **Likely cause** -> **Fix** pattern. Citations point at the
code or docs where the behavior is defined.

---

## 1. `claude-panes: command not found`

**Symptom.** Shell reports `claude-panes: command not found` (POSIX) or
`'claude-panes' is not recognized` (cmd.exe) right after install.

**Likely cause.** Install scripts copy a wrapper into a user-local bin but
never mutate `PATH`. `install.ps1` installs to `$env:USERPROFILE\.local\bin`
(`install.ps1:22`) and refuses to touch `PATH` (`install.ps1:86-100`).
`install.sh` installs to `$HOME/.local/bin` (`install.sh:22`) and refuses to
edit any rc file (`install.sh:96-131`).

**Fix.** Add the install directory to `PATH`. The installers print the exact
command on stderr: PowerShell at `install.ps1:97`, POSIX/fish at
`install.sh:120-127`. Open a new shell after applying. Or re-install with
`-p <path>` / `-InstallPath <path>` pointing at a directory already on `PATH`.

---

## 2. `error: no supported terminal installed` (exit 3)

**Symptom.** Exit code `3` with
`no supported terminal found on PATH; tried: wt, wezterm, tmux, zellij`.

**Likely cause.** None of `wt`, `wezterm`, `tmux`, `zellij` resolve on `PATH`.
`detect_terminal` walks `ADAPTER_PRIORITY` and raises `NoTerminalError` when
every `is_available()` returns `False` (`claude_panes.py:351-356`). Each
adapter is just `shutil.which(<binary>)`
(`claude_panes.py:402-405, 463-464, 528-529, 600-601`); `wt` also requires
`sys.platform == "win32"`.

**Fix.** Install one of:

- **Windows Terminal (`wt`):** preinstalled on Windows 11. On Windows 10,
  Microsoft Store or `winget install Microsoft.WindowsTerminal`. `wt.exe` is
  an execution alias under `%LOCALAPPDATA%\Microsoft\WindowsApps`, on `PATH`
  by default (`docs/terminal-adapters.md:38-41`).
- **WezTerm:** `winget install wez.wezterm` / `brew install --cask wezterm`,
  or https://wezterm.org. Verify with `wezterm --version`.
- **tmux:** POSIX only. `apt install tmux` / `brew install tmux`. On Windows
  see item 6.
- **Zellij:** `cargo install zellij` or https://zellij.dev. Native Windows
  binaries ship from 0.44.0 (`docs/terminal-adapters.md:539-541`).

Re-run `claude-panes detect`; at least one row must show a real path.

---

## 3. TOML parse errors on `start` or `validate`

**Symptom.** Exit code `2` with `<path>: invalid TOML: <parser message>`
(`claude_panes.py:238-239`).

**Likely causes.** Literal strings (`'...'`) are verbatim and cannot contain
a `'` - `cmd = 'bash -lc 'cd && claude''` terminates at the second `'`. Basic
strings (`"..."`) need `\"` for embedded `"` - `cmd = "wsl bash -lc "claude""`
closes the string at the second `"`.

**Fix.** Pick one quoting style. For embedded `'`, use a basic string with
`\"` for inner double quotes:
`cmd = "wsl -- bash -lc \"cd ~/work && claude\""`. For embedded `"`, use a
triple-quoted literal: `cmd = '''wsl -- bash -lc "cd ~/work && claude"'''`.
ClaudePanes does not re-quote or parse `cmd`; whatever the TOML parser
returns goes verbatim to the multiplexer (`docs/config-format.md:88-91,
261-269`).

---

## 4. Windows Terminal opens but no panes split

**Symptom.** `wt.exe` launches the first pane only; `split-pane` actions are
silently dropped.

**Likely cause.** Old `wt.exe` builds parse the `;` action-chain separator
inconsistently. ClaudePanes inserts a bare `;` between sub-commands
(`claude_panes.py:414-417`) and routes via `cmd.exe /c` so the `;` survives
the parent shell (`claude_panes.py:408-410`;
`docs/terminal-adapters.md:111-142`). Builds before ~1.12 drop the chain.

**Fix.** Check `wt --version` and upgrade via Microsoft Store or
`winget upgrade Microsoft.WindowsTerminal`. The smoke test at
`docs/terminal-adapters.md:188-193` (`wt new-tab cmd /k echo hello`) verifies
the executable; if it fails, the install itself is broken.

---

## 5. WezTerm pane-id capture failure

**Symptom.** `claude-panes start ...` errors with
`wezterm exited with code <n>: <stderr>`, or later splits fail because the
captured pane-id was empty.

**Likely cause.** `WezTermAdapter._spawn_capturing_id` captures stdout from
`wezterm cli spawn` and feeds it to the next `--pane-id`
(`claude_panes.py:506-521`). `wezterm cli` talks to a running WezTerm GUI
over the mux protocol (`docs/terminal-adapters.md:210-213`); if no GUI is
running and the spawn fails, stdout is empty and the empty string flows into
the next call.

**Fix.** Launch the WezTerm GUI first, then re-run ClaudePanes. Verify the
mux is healthy with the smoke test at `docs/terminal-adapters.md:350-356`:

```bash
wezterm cli spawn -- echo hello
```

Stdout must be a single integer pane-id. If it is empty or non-numeric, fix
WezTerm before retrying.

---

## 6. tmux on Windows: `command not found`

**Symptom.** On a native Windows shell, `claude-panes detect` shows
`tmux  not found` and `--terminal tmux` exits 3 with
`terminal 'tmux' requested but its binary (tmux) was not found on PATH`.

**Likely cause.** tmux is POSIX-only. `TmuxAdapter.is_available()` is a plain
`shutil.which("tmux")` check (`claude_panes.py:528-529`); on native Windows
it always returns `False`.

**Fix.** Per ADR-013 (`docs/design-decisions.md:364-379`), ClaudePanes does
not auto-wrap tmux with `wsl.exe`. Invoke ClaudePanes from inside WSL:

```bash
wsl -d Ubuntu
# inside WSL:
sudo apt install tmux
claude-panes start <layout> --terminal tmux
```

Inside WSL, `shutil.which("tmux")` resolves and the adapter detects normally.

---

## 7. Zellij KDL parse error

**Symptom.** Zellij exits non-zero with a KDL parse error referring to the
generated `layout.kdl` (the temp path is surfaced in the message;
`docs/terminal-adapters.md:559-563`).

**Likely cause.** `_kdl_pane_line` embeds the user's raw `cmd` in a KDL string
argument: `args "/c" "<cmd>"` on Windows or `args "-lc" "<cmd>"` on POSIX
(`claude_panes.py:718-727`). `_kdl_escape` (`claude_panes.py:709-710`) only
runs over the literal `cmd.exe` / `bash` head, not the embedded user `cmd`,
so an unescaped `"` or `\` inside `cmd` breaks the KDL string.

**Fix.** Use a triple-quoted TOML literal so the value can carry raw `"`:

```toml
[[panes]]
cmd = '''bash -lc "cd ~/work && claude"'''
```

Inspect the generated KDL with
`claude-panes start <layout> --terminal zellij --dry-run`; the renderer
prints the full KDL to stderr before launching
(`claude_panes.py:609-613`).

---

## 8. `claude` not found inside the spawned pane

**Symptom.** The pane opens but immediately prints `claude: command not found`
or `'claude' is not recognized`.

**Likely cause.** Every adapter hands `cmd` to a shell verbatim - WezTerm and
Zellij wrap via `_shell_wrap` (`claude_panes.py:682-691`) and
`_kdl_pane_line` (`claude_panes.py:713-733`); `wt` and tmux delegate to the
host shell. ClaudePanes never mutates `PATH` and never resolves binaries
itself. If `claude` is not on `PATH` inside the pane's shell (typical under
`wsl.exe -- bash -lc ...` if the rc file does not run), the lookup fails.

**Fix.**

- For WSL panes, use `bash -lc` (a login shell) so rc files run. The worked
  example at `docs/terminal-adapters.md:163-179` uses
  `bash -lc 'cd ~/work/foo && claude'` for this reason.
- Smoke-test from outside ClaudePanes:
  `wsl -d Ubuntu -- bash -lc 'which claude'`. Must print a path.
- Otherwise install Claude Code in that environment, or invoke it by absolute
  path: `cmd = "wsl -- bash -lc '/home/me/.local/bin/claude'"`.

---

## 9. `working_dir` not honored

**Symptom.** The pane opens in your home directory or ClaudePanes' launch
directory even though the TOML sets `working_dir`.

**Likely causes.**

- **Typo.** `working_dir` is validated only as a string
  (`claude_panes.py:267-269`); a misspelled key like `workingDir` becomes an
  unknown-key warning, not an error (`claude_panes.py:246`;
  `docs/config-format.md:386-389`).
- **`~` used in `cmd` instead of `working_dir`.** ClaudePanes only expands
  `~` and env vars for `working_dir`: `_expand` is invoked on
  `layout.working_dir` and `pane.working_dir` exclusively
  (`claude_panes.py:422, 425, 441, 481, 498, 549, 560, 571, 581`).
  `docs/config-format.md:403-406` states this explicitly: tilde and env
  expansion apply to `working_dir` and nowhere else.

**Fix.**

- Run `claude-panes validate <layout>` and read stderr; rename keys flagged
  by `unknown key 'workingDir' in ...` warnings to `working_dir`.
- Use `--dry-run` to see the rendered argv. Each adapter passes the expanded
  path as a flag (`--startingDirectory` for `wt`, `--cwd` for `wezterm`,
  `-c` for tmux). If the dry-run still shows a literal `~`, the path is
  riding inside `cmd` - move it to `working_dir`.
- If you want `~` expanded inside `cmd`, let the spawned shell do it:
  `bash -lc 'cd ~/work && claude'`.
