# Terminal Adapters

ClaudePanes is a zero-dependency Python launcher that opens pre-split terminal
panes running pre-configured commands. The "adapter" is the per-terminal
translator: it takes the in-memory `Layout` parsed from the user's TOML config
and emits the CLI invocation that asks the host terminal to realize that
layout.

This document covers each supported adapter:

1. [Windows Terminal](#1-windows-terminal-wtexe) (`wt.exe`)
2. [WezTerm](#2-wezterm-wezterm-cli) (`wezterm cli`)
3. [tmux](#3-tmux)
4. [Zellij](#4-zellij)

It ends with the [adapter interface contract](#adapter-interface-contract) and
the [detection priority and override rules](#priority-and-override).

For each adapter, we document detection, command shape, a worked example
(one tab with two vertical-split panes), known quirks, and a smoke-test
command you can paste into a shell to verify the terminal is wired up.

---

## 1. Windows Terminal (`wt.exe`)

### Detection

```python
import shutil, sys

def is_available() -> bool:
    if sys.platform != "win32":
        return False
    return shutil.which("wt") is not None
```

`wt.exe` ships as an execution alias under `%LOCALAPPDATA%\Microsoft\WindowsApps`,
which is on `PATH` by default on Windows 11. It is not available on macOS or
Linux. WSL users can call it as `cmd.exe /c wt.exe ...`, but ClaudePanes treats
that as out-of-scope — if a user is in WSL they should pick the `tmux` adapter.

### Command shape

```
wt [options] new-tab [nt-options] [commandline]
   ; split-pane [-V|-H] [sp-options] [commandline]
   ; split-pane [-V|-H] [sp-options] [commandline]
   ...
```

The literal `;` is `wt`'s own sub-command separator — it is not the shell
separator. `-V` (vertical) puts the new pane to the right of the focused one;
`-H` (horizontal) puts it below.

### Flags ClaudePanes emits

| Flag                          | Sub-command            | Source                                    |
| ----------------------------- | ---------------------- | ----------------------------------------- |
| `--title <text>`              | `new-tab`              | `tabs[*].title` / synthesized tab title   |
| `--startingDirectory <path>`  | `new-tab`, `split-pane`| `layout.working_dir`, `panes[*].working_dir` |
| `-V` / `-H`                   | `split-pane`           | `panes[*].split`                          |
| `-s <fraction>`               | `split-pane`           | `panes[*].size` (passed as a `0.0`–`1.0` decimal) |

`--startingDirectory` is emitted at both layout level (from
`layout.working_dir` on `new-tab`) and pane level (from `panes[*].working_dir`
on the sub-command that creates that pane). When both are set on the same
`new-tab` invocation, the **pane-level value wins**: `wt` honors the last
matching flag on its argv, and ClaudePanes appends the pane-level
`--startingDirectory` after the layout-level one.

`-s` accepts a decimal between `0.0` and `1.0` exclusive (e.g. `-s 0.4`
gives the new pane 40% of the parent). ClaudePanes passes `panes[*].size`
through unchanged — it is not converted to a percent string. See
https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments for
the full flag reference.

### Worked example

Layout: one tab titled `dev`, two vertical-split panes — left runs `cmd /k dir`,
right runs `wsl.exe -d Ubuntu-22.04 -- bash -lc "claude"`.

Target invocation (Command Prompt syntax):

```cmd
wt new-tab --title dev cmd /k dir ; split-pane -V wsl.exe -d Ubuntu-22.04 -- bash -lc "claude"
```

The exact `subprocess.run` argv list ClaudePanes builds (we always invoke
through `cmd.exe /c` to sidestep PowerShell's `;` quirk — see below):

```python
argv = [
    "cmd.exe", "/c", "wt.exe",
    "new-tab", "--title", "dev",
    "cmd", "/k", "dir",
    ";",
    "split-pane", "-V",
    "wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", "claude",
]
subprocess.run(argv, check=True)
```

Note that the `;` is its own argv element. When `wt.exe` is invoked through
`cmd.exe /c`, cmd does not treat bare `;` as a separator, so it gets passed
straight through to `wt`, which then interprets it as its own sub-command
delimiter.

### Critical quirk: the semicolon problem

The Microsoft Learn docs are explicit:

> PowerShell uses a semicolon `;` to delimit statements. To interpret a
> semicolon `;` as a command delimiter for wt command-line arguments, you need
> to escape semicolon characters by using backticks.
> — https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments

This means the same string `wt new-tab cmd ; split-pane -V wsl` behaves
differently depending on the parent shell:

| Parent shell | What happens                                                         |
| ------------ | -------------------------------------------------------------------- |
| `cmd.exe`    | `;` reaches `wt` intact. Works.                                      |
| PowerShell   | `;` is consumed by PowerShell as a statement separator. Broken.      |
| bash (WSL)   | `;` is consumed by bash as a statement separator. Broken.            |

Three viable strategies exist:

1. **Invoke via `cmd.exe /c`** (ClaudePanes default). The argv list above
   contains a bare `;` element; `cmd.exe /c` does not interpret it, so `wt`
   gets it verbatim. This works regardless of which shell launched
   ClaudePanes.

2. **Escape with backtick when generating a PowerShell string.** Only relevant
   if we ever emit a *string* for the user to paste; for `subprocess.run` with
   `shell=False` we use strategy 1.

3. **Use PowerShell's `--%` stop-parsing operator.** Tells PowerShell to pass
   everything after it verbatim. Fragile because it disables all variable
   expansion for the rest of the line.

ClaudePanes uses strategy 1 unconditionally.

### Argument quoting

For Windows targets, `subprocess.run(argv, shell=False)` will quote the argv
elements using the rules `subprocess.list2cmdline` implements (which match
Microsoft's CRT parsing rules). This is exactly what we want: spaces in titles
or commands are handled correctly without us hand-rolling quotes.

```python
import subprocess
subprocess.list2cmdline(["new-tab", "--title", "My Dev Tab", "cmd", "/k", "dir"])
# 'new-tab --title "My Dev Tab" cmd /k dir'
```

The one element we must NOT let `list2cmdline` touch is the `;` separator — but
since `;` contains no whitespace or quotes, `list2cmdline` leaves it as a bare
`;`, which is what `wt` wants.

### WSL example

For a pane that runs Claude Code inside Ubuntu-22.04 under WSL, change to
`~/work/foo` first:

```cmd
wt new-tab wsl.exe -d Ubuntu-22.04 -- bash -lc "cd ~/work/foo && claude"
```

argv:

```python
argv = [
    "cmd.exe", "/c", "wt.exe",
    "new-tab",
    "wsl.exe", "-d", "Ubuntu-22.04", "--",
    "bash", "-lc", "cd ~/work/foo && claude",
]
```

The `--` after `Ubuntu-22.04` tells `wsl.exe` that everything that follows is
the command to run inside the distribution.

### Smoke test

Paste into Command Prompt (Win+R, `cmd`, Enter):

```cmd
wt new-tab cmd /k echo hello
```

You should see Windows Terminal open with a tab running `cmd` that printed
`hello` and stayed open (`/k` = keep open after command).

### Source

- https://learn.microsoft.com/en-us/windows/terminal/command-line-arguments

---

## 2. WezTerm (`wezterm cli`)

### Detection

```python
def is_available() -> bool:
    return shutil.which("wezterm") is not None
```

WezTerm is cross-platform (Windows, macOS, Linux). The `wezterm cli`
sub-command talks to a running WezTerm GUI via its mux protocol — if no GUI is
running, `wezterm cli spawn --new-window` will start one.

### Command shape

WezTerm's CLI is **imperative and stateful**: it returns pane IDs from each
call, and you feed those IDs back into subsequent calls. There is no single
"open this whole layout" invocation.

```
wezterm cli spawn --new-window -- <cmd>           # prints pane-id of new pane
wezterm cli split-pane --pane-id <id> --right -- <cmd>   # prints new pane-id
wezterm cli split-pane --pane-id <id> --bottom -- <cmd>  # prints new pane-id
```

Direction flags (verified against
https://wezterm.org/cli/cli/split-pane.html):

| Flag       | Result                                                |
| ---------- | ----------------------------------------------------- |
| `--right`  | new pane to the right of target (aka `--horizontal`)  |
| `--left`   | new pane to the left of target                        |
| `--bottom` | new pane below target (this is the default)           |
| `--top`    | new pane above target                                 |

Note that `--horizontal` is an alias for `--right`, which is the opposite
convention from `wt`'s `-H` (which means "split horizontally, new pane below").
The adapter normalizes this in `_translate_direction`.

### Flags ClaudePanes emits

| Flag                | Sub-command            | Source                                            |
| ------------------- | ---------------------- | ------------------------------------------------- |
| `--new-window`      | `spawn` (first tab only) | implicit; opens a fresh window for the layout   |
| `--cwd <path>`      | `spawn`, `split-pane`  | `panes[*].working_dir` or `layout.working_dir`    |
| `--percent <int>`   | `split-pane`           | `panes[*].size` (derived as `int(size * 100)`, must be 1–99) |
| `--right` / `--bottom` / `--left` / `--top` | `split-pane` | `panes[*].split`                |
| `--pane-id <id>`    | `split-pane`           | captured from a previous `spawn` / `split-pane` stdout |

### Multi-tab behavior

WezTerm doesn't have a single "open this multi-tab workspace" CLI call,
so ClaudePanes drives it tab by tab:

- The **first pane of the first tab** invokes `wezterm cli spawn --new-window
  -- <cmd>`. This is the only invocation that uses `--new-window`; it
  guarantees a clean WezTerm window even when another WezTerm GUI is already
  running.
- The **first pane of each subsequent tab** invokes `wezterm cli spawn`
  *without* `--new-window`, so WezTerm opens a new tab inside the window
  spawned in step one rather than a separate window.
- Splits inside each tab invoke `wezterm cli split-pane --pane-id <id>` with
  the appropriate direction and `--percent` flag.

### Worked example

Layout: one window with two vertical-split panes — left runs `claude`, right
runs `npm run dev`.

Pseudocode for the adapter's `execute`:

```python
def execute(self, layout: Layout, dry_run: bool = False) -> int:
    panes = []  # parallel list to layout.panes, holds wezterm pane-ids

    # First pane: spawn a new window.
    cmd1 = ["wezterm", "cli", "spawn", "--new-window", "--", "claude"]
    if dry_run:
        print(" ".join(cmd1))
        first_id = "<id1>"
    else:
        first_id = subprocess.run(
            cmd1, check=True, capture_output=True, text=True
        ).stdout.strip()
    panes.append(first_id)

    # Second pane: split the first pane to the right.
    cmd2 = [
        "wezterm", "cli", "split-pane",
        "--pane-id", first_id,
        "--right",
        "--", "npm", "run", "dev",
    ]
    if dry_run:
        print(" ".join(cmd2))
    else:
        second_id = subprocess.run(
            cmd2, check=True, capture_output=True, text=True
        ).stdout.strip()
        panes.append(second_id)

    return 0
```

The full argv lists ClaudePanes runs:

```python
# Step 1
["wezterm", "cli", "spawn", "--new-window", "--", "claude"]
# stdout: "12\n"  (pane-id 12)

# Step 2
["wezterm", "cli", "split-pane", "--pane-id", "12", "--right", "--", "npm", "run", "dev"]
# stdout: "13\n"  (pane-id 13)
```

### Critical quirk: sequential execution with state

Unlike `wt`, where the entire layout is one process invocation, WezTerm
requires N+M subprocesses for N panes (1 spawn + N-1 splits). This means:

- `build_command` cannot return a single argv list. The adapter either returns
  a `list[list[str]]` (and the runner threads stdout from step k into step
  k+1's `--pane-id`), or overrides `execute` directly.
- ClaudePanes uses the second approach: WezTerm's adapter implements its own
  `execute` and treats `build_command` as a no-op that raises
  `NotImplementedError`. See the [interface
  contract](#adapter-interface-contract) below.
- `dry_run` mode prints each subprocess invocation with `<id1>`, `<id2>`,
  etc. as placeholders since we cannot know the real IDs without running.

### Alternative: Lua config

WezTerm supports loading a Lua config file via `wezterm start --config-file
layout.lua`. The Lua file can define a static workspace with named panes. This
is more powerful (it can set keybindings, color schemes per pane, etc.) but
has two downsides for our use case:

1. We must write a Lua file every run (or maintain one alongside the TOML),
   doubling the config surface.
2. Lua's syntax for defining panes is verbose; generating it from our `Layout`
   shape is awkward enough that we'd want a template engine, which conflicts
   with the zero-dependency rule.

ClaudePanes uses the `cli spawn` / `cli split-pane` approach. Power users who
need Lua features can pre-write their own `layout.lua` and reference it from
TOML via a future `wezterm_lua_config` key (not yet implemented).

### Smoke test

```bash
wezterm cli spawn -- echo hello
```

A new tab opens in the running WezTerm (or a new window starts), runs `echo
hello`, and exits. Stdout from the `wezterm cli spawn` call should be a
single integer (the pane-id) on its own line.

### Sources

- https://wezterm.org/cli/cli/spawn.html — spawn returns the pane-id on stdout
- https://wezterm.org/cli/cli/split-pane.html — direction flags and `--pane-id`

---

## 3. tmux

### Detection

```python
def is_available() -> bool:
    return shutil.which("tmux") is not None
```

tmux is Unix-only. On Windows it works inside WSL2 (Ubuntu, Debian, etc.) but
not against PowerShell or cmd.exe directly. If ClaudePanes is launched from
Windows native Python and the user's TOML asks for tmux, the adapter raises a
descriptive error pointing the user at WSL.

### Command shape

tmux composes a layout in a single command line by chaining `tmux` subcommands
with a literal `;`. Like `wt`, the `;` is consumed by tmux itself, not by the
shell — which means escaping rules differ between shell-string form and argv
form.

```
tmux new-session -d -s <name> "<cmd1>" \;
     split-window -h "<cmd2>" \;
     split-window -v "<cmd3>" \;
     attach -t <name>
```

| Flag                 | Result                                          |
| -------------------- | ----------------------------------------------- |
| `split-window -h`    | split horizontally — new pane on the **right**  |
| `split-window -v`    | split vertically — new pane on the **bottom**   |
| `new-session -d`     | create detached, do not attach immediately      |
| `new-session -s NAME`| name the session                                |
| `new-session -A`     | attach to existing session with same name, else create |

Note: tmux's `-h` and `-v` use the opposite convention from `wt`. tmux `-h`
means "split along a horizontal axis, panes side by side"; `wt -H` means
"new pane is horizontally adjacent below". The adapter normalizes this.

### Flags ClaudePanes emits

| Flag             | Sub-command                         | Source                                                |
| ---------------- | ----------------------------------- | ----------------------------------------------------- |
| `-s <session>`   | `new-session`                       | `layout.name` plus a millisecond timestamp suffix     |
| `-n <window>`    | `new-session`, `new-window`         | `tabs[*].title` when set                              |
| `-d`             | `new-session`                       | always — keep session detached while we add panes     |
| `-t <session>`   | `new-window`, `split-window`        | targets the session we just created                   |
| `-c <cwd>`       | `new-session`, `new-window`, `split-window` | `panes[*].working_dir` or `layout.working_dir` |
| `-h` / `-v`      | `split-window`                      | `panes[*].split`                                      |
| `-p <int>`       | `split-window`                      | `panes[*].size` (derived as `int(size * 100)`, a percent 1–99) |

#### Known follow-up: `-p` deprecation

tmux 3.4 deprecated `-p` in favor of `-l <int>%` (length-as-percent). The
old flag still works on every tmux release in common distribution channels
as of v0.1.0, so ClaudePanes keeps emitting `-p`. Migrating to `-l` is
tracked as a Phase 2 follow-up; the switch is purely lexical (replace `-p`
with `-l` and append `%` to the value) and breaks nothing for callers.

### Tabs map to tmux windows

tmux has no first-class "tab" concept — what other multiplexers call a tab
is a tmux *window*. ClaudePanes maps the two like this:

- The **first tab** is the initial window created by `new-session`. Its
  panes (anchor + splits) are added in the same compound invocation.
- **Each subsequent tab** invokes `new-window -t <session>`, optionally with
  `-n <title>` and `-c <cwd>`, followed by the same `split-window` chain
  for that tab's extra panes.
- All `-t <session>` targets use the session name only (no
  `:window.pane` addressing), so tmux's "active window / active pane"
  defaults apply.

### Worked example

Layout: one session named `claudepanes`, two vertical-split panes — left
runs `claude`, right runs `npm run dev`.

Shell form (bash, what a user would type):

```bash
tmux new-session -d -s claudepanes 'claude' \; \
     split-window -h -t claudepanes 'npm run dev' \; \
     attach -t claudepanes
```

In shell form the `\;` is a backslash-escaped semicolon: the backslash tells
bash not to terminate the command, and tmux then sees the `;` as its own
sub-command delimiter.

argv form (what `subprocess.run` with `shell=False` actually gets):

```python
argv = [
    "tmux",
    "new-session", "-d", "-s", "claudepanes", "claude",
    ";",
    "split-window", "-h", "-t", "claudepanes", "npm run dev",
    ";",
    "attach", "-t", "claudepanes",
]
subprocess.run(argv, check=True)
```

When using `shell=False`, every argv element is passed verbatim to `execve`.
The bare `;` element reaches tmux untouched — exactly what tmux wants. There
is no backslash because we are not going through a shell.

### Critical quirks

**1. `\;` vs `;` depending on `shell=`.**

| Invocation form                          | Separator |
| ---------------------------------------- | --------- |
| `subprocess.run(argv, shell=False)`      | `";"`     |
| `subprocess.run("...", shell=True)`      | `"\\;"`   |
| User typing into bash                    | `\;`      |

ClaudePanes uses `shell=False` everywhere; the adapter inserts plain `";"`
elements between sub-commands.

**2. Detach-then-attach pattern.**

`tmux new-session` without `-d` blocks the calling process while the session
runs in the foreground. ClaudePanes needs to:

1. create the session detached (`-d`),
2. add all the splits and configure them,
3. attach at the end (or let the user attach manually).

The `-A` flag is an attractive shortcut (attach-or-create) but it changes
behavior when the session already exists — splits get added to an existing
session, which is usually not what the user wants. ClaudePanes generates a
fresh session name by default to avoid this: the format is
`{layout.name}-{ms_timestamp}` (e.g. `feature-x-1716192345123`), so
relaunching the same layout always produces a brand-new session and never
collides with one a previous run left behind.

**3. Command quoting inside tmux.**

When the pane command contains spaces (`npm run dev`), tmux treats the whole
argv element as one command string and parses it with its own quoting rules.
We pass the command as a single argv element; tmux's parser handles word
splitting. If the user's command contains a literal `;`, the user must escape
it in their TOML — we do not double-escape.

### Smoke test

In a Unix shell or WSL:

```bash
tmux new-session -d -s smoke 'echo hello; sleep 30'; tmux attach -t smoke
```

You should attach to a session showing `hello` and idling for 30 seconds.
Detach with `Ctrl-B d`.

### Source

- https://man.openbsd.org/tmux.1

---

## 4. Zellij

### Detection

```python
def is_available() -> bool:
    return shutil.which("zellij") is not None
```

As of Zellij 0.44.0 (released March 2026) Zellij ships native Windows
binaries, so detection works the same way on every platform.

### Command shape — declarative KDL

Zellij has two surface areas: the `zellij action` CLI (which manipulates a
*running* session) and KDL layout files (which describe a layout
declaratively and are passed at startup). `zellij action` is awkward for
ClaudePanes because it requires an attached session already, and the
action-by-action protocol is verbose. KDL layouts are first-class.

ClaudePanes writes a temporary `.kdl` file from the in-memory `Layout` and
invokes:

```
zellij --layout /tmp/claudepanes-<rand>/layout.kdl
```

The temp directory is created via `tempfile.TemporaryDirectory(prefix=
"claudepanes-")` (or its `mkdtemp` equivalent) and the KDL document is
written to a fixed filename `layout.kdl` inside it. Using a directory per
launch (rather than a single `NamedTemporaryFile`) gives Zellij a stable,
human-readable filename to surface in any error messages while still
isolating each run. The directory and its `layout.kdl` are cleaned up when
the `zellij --layout <path>` subprocess returns.

### KDL layout syntax

Verified against
https://zellij.dev/documentation/creating-a-layout:

```kdl
layout {
    tab name="dev" {
        pane split_direction="vertical" {
            pane command="claude"
            pane command="npm" {
                args "run" "dev"
            }
        }
    }
}
```

Two syntax notes that bit us during prototyping:

- `command="..."` takes a single executable name. Arguments go in a nested
  `args "a" "b" "c"` child node — they are NOT space-separated inside the
  `command` string. `command="npm run dev"` will try to exec a file literally
  named `npm run dev`.
- `split_direction="vertical"` means **the dividing line is vertical**, so
  panes end up **side by side** (left/right). `"horizontal"` puts them
  stacked. This is the opposite of what "vertical split" means in most
  English-language docs. We document this in our user-facing TOML reference
  too.

### Worked example

Layout: one tab named `dev`, two vertical-split panes — left runs `claude`,
right runs `npm run dev`.

Generated KDL (written to `/tmp/claudepanes-abc123.kdl`):

```kdl
layout {
    tab name="dev" {
        pane split_direction="vertical" {
            pane command="claude"
            pane command="npm" {
                args "run" "dev"
            }
        }
    }
}
```

argv:

```python
argv = ["zellij", "--layout", "/tmp/claudepanes-abc123.kdl"]
subprocess.run(argv, check=True)
```

### How ClaudePanes renders `cmd` into KDL

The user-facing `cmd` is a single shell command line, but Zellij's KDL
`command="..."` field takes a single executable plus an `args` child node
(no space-splitting). ClaudePanes bridges the gap by always wrapping `cmd`
in a host shell, the same intent as the other adapters:

- **POSIX hosts:** `pane command="bash" { args "-lc" "<cmd>" }`
- **Windows hosts:** `pane command="cmd.exe" { args "/c" "<cmd>" }`

The wezterm and tmux adapters share a common helper (`_shell_wrap`) that
picks the POSIX shell at runtime: the user's login shell from `$SHELL`
with `-lc` when that variable is set, falling back to `/bin/sh -c` when it
is not (Windows always uses `cmd.exe /c`). The Zellij KDL renderer emits a
fixed `bash` head as shown above because the generated layout file is a
static artifact rather than a live argv; on a host without `bash` on
`PATH`, prefer the wezterm or tmux adapter, which honor `$SHELL`.

Either way this guarantees that shell metacharacters, pipes, quoting, and
the `[shell].prelude` ` && ` join behave the same way across wt, wezterm,
tmux, and zellij. The user never has to think about Zellij's exec-style
`command` semantics.

### How `panes[*].size` is rendered

Zellij's KDL accepts pane sizes only as percent strings. ClaudePanes
converts `panes[*].size` (a float between `0.0` and `1.0`) to the form
Zellij wants:

```kdl
pane command="bash" size="40%" {
    args "-lc" "claude"
}
```

Note the percent sign inside the quoted string — Zellij rejects a bare
integer or a fraction here.

### Critical quirks

**1. `command` vs `args`.** As above: arguments must be a child node, not
appended to `command`.

**2. `split_direction` is the orientation of the divider, not the
arrangement.** `vertical` means side-by-side. The adapter accepts both
ClaudePanes-internal names (`left-right`, `top-bottom`) and translates them.

**3. Layouts are read-only once started.** You cannot edit the `.kdl` file
mid-session and expect Zellij to pick up changes. The temp file is therefore
safe to delete as soon as Zellij has started — but ClaudePanes waits for
`subprocess.run` to return before unlinking, in case Zellij re-reads the
file on session resume.

**4. The session is named after the layout file by default.** If you launch
the same layout twice in a row, Zellij will say "a session with that name
already exists" and refuse. ClaudePanes generates a fresh temp directory
per launch (so the layout-file path differs every time) to side-step this.

### Known limitations (v0.1.0)

The KDL renderer in ClaudePanes v0.1.0 supports **only one
`split_direction` per tab**. Internally, every pane after the anchor in a
tab is emitted as a sibling inside a single `pane split_direction="…"`
block, where the direction is taken from the **second pane's**
`split` value.

That means a TOML layout that mixes `split = "vertical"` and
`split = "horizontal"` *within the same tab* will validate (config
validation is direction-agnostic) but will not render faithfully under
Zellij — every pane in the tab ends up arranged along the first
direction encountered.

This is fine for the most common case (Claude on the left, a stack of
side panes on the right, all sharing one `split_direction`), but it
breaks T-shaped and L-shaped layouts on Zellij specifically. The other
three adapters render mixed-direction tabs correctly.

**Workaround for v0.1.0:** put non-uniform splits in separate tabs, or
pick a different adapter for that layout. **Phase 3 plan:** emit nested
`pane split_direction="…" { … }` blocks per the actual pane tree so
ClaudePanes can render arbitrary trees.

### Smoke test

On any platform with Zellij installed:

```bash
echo 'layout { tab { pane command="echo" { args "hello" } } }' > /tmp/smoke.kdl && zellij --layout /tmp/smoke.kdl
```

Zellij should open, run `echo hello` in the only pane, and exit when you
press the close-pane chord (default `Ctrl-P x`).

### Source

- https://zellij.dev/documentation/layouts
- https://zellij.dev/documentation/creating-a-layout

---

## Adapter interface contract

Every adapter implements this Protocol (matches `architecture.md`):

```python
from typing import Protocol

class Adapter(Protocol):
    name: str    # short identifier, e.g. "wt", "wezterm", "tmux", "zellij"
    binary: str  # name to look up via shutil.which

    def is_available(self) -> bool:
        """True if the adapter's terminal binary is on PATH and usable on this OS."""
        ...

    def build_command(self, layout: Layout) -> list[str] | str:
        """Return the argv list (or shell string) that opens `layout`.

        Adapters that need stateful multi-step execution (e.g. WezTerm) may
        raise NotImplementedError here and override `execute` directly.
        """
        ...

    def execute(self, layout: Layout, dry_run: bool = False) -> int:
        """Run the command(s). Return the process exit code (0 on success).

        If `dry_run` is True, print the planned argv lists to stdout and
        return 0 without launching anything.
        """
        ...
```

**Single-shot adapters** (`wt`, `tmux`, `zellij`) implement `build_command`
and rely on the default `execute`, which is just
`subprocess.run(self.build_command(layout), check=True).returncode`.

**Multi-step adapters** (`wezterm`) override `execute`, raise
`NotImplementedError` from `build_command`, and manage their own
state-threading between subprocess calls. See the
[WezTerm worked example](#worked-example-1) for the pattern.

To add a fifth adapter (say, Kitty):

1. Add a module `claudepanes/adapters/kitty.py`.
2. Implement the Protocol above.
3. Register it in `claudepanes/adapters/__init__.py`'s `ADAPTERS` list,
   choosing a priority position.
4. Add a section to this document.

---

## Priority and override

When multiple terminals are installed, ClaudePanes picks the first available
adapter from this default priority list:

1. `wt` — most Windows users have it, fastest to launch on Windows.
2. `wezterm` — strongest cross-platform feature set, but only present if the
   user installed it deliberately.
3. `tmux` — venerable, near-universal on Unix, the safe fallback.
4. `zellij` — newest, smallest installed base, but explicit Windows support
   makes it a credible cross-platform option.

This list is the source of truth for the launcher's auto-detection order
and is mirrored verbatim in code as `ADAPTER_PRIORITY: tuple[str, ...] =
("wt", "wezterm", "tmux", "zellij")` in `claude_panes.py`. If the two
ever diverge, the code wins (because that is what actually runs); treat
that as a doc bug and update this section.

Override mechanisms (highest priority first):

1. `--terminal wezterm` on the command line.
2. `terminal = "wezterm"` in the TOML config's top-level table.
3. Default priority list above.

If the requested adapter's binary is not on `PATH`, ClaudePanes exits
non-zero with a message that lists which adapters *are* available and how to
install the missing one.
