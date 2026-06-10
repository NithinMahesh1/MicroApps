# ClaudePanes CLI Specification

This document defines the exact command-line surface for ClaudePanes. It is the
contract between the user-facing CLI and the implementation: anything described
here is in scope for the MVP and will appear in code; anything not described
here is out of scope for the MVP.

ClaudePanes is a zero-dependency single-file Python launcher (Python 3.11+,
stdlib only). It reads a TOML layout config and opens the requested pane layout
in whichever terminal multiplexer is installed (Windows Terminal `wt.exe`,
WezTerm, tmux, Zellij).

## 1. Invocation

The tool is invoked as `claude-panes`. After install, the entry point is
expected to be on `PATH`.

```
claude-panes <subcommand> [args...] [flags...]
```

Running `claude-panes` with no subcommand prints the top-level help and exits
with code `0`. Running `claude-panes --help` or `claude-panes -h` does the
same.

The top-level help lists every available subcommand and the global flags.

## 2. Subcommands

The following subcommands are available:

- `start` — open a layout in the host terminal.
- `list` — list known layouts.
- `validate` — parse and validate a layout without executing it.
- `detect` — report which terminals are installed.
- `version` — print the tool and interpreter version.

Each subcommand is documented below.

### 2.1 `claude-panes start`

#### Synopsis

```
claude-panes start <layout> [--terminal {wt|wezterm|tmux|zellij}]
                            [--dry-run]
                            [--verbose | -v]
                            [--config-dir <path>]
                            [--help | -h]
```

#### Description

The primary command. Resolves the named layout, selects an adapter for the
host terminal, constructs the spawn command, and either prints it (with
`--dry-run`) or executes it. ClaudePanes exits immediately after spawning; the
terminal multiplexer owns the lifecycle of the panes it created.

#### Positional arguments

- `<layout>` — layout name. Resolved as follows:
  1. If the value contains a path separator (`/` or `\`) or ends in `.toml`,
     it is treated as a file path. Relative paths resolve against the current
     working directory.
  2. Otherwise it is treated as a layout name and looked up at
     `~/.config/claude-panes/layouts/<layout>.toml`. The `--config-dir` flag
     overrides the `~/.config/claude-panes` root.

#### Flags

- `--terminal {wt|wezterm|tmux|zellij}` — override auto-detection. Forces the
  named adapter even if other terminals are installed. If the named terminal
  is not installed, the command exits with code `3`.
- `--dry-run` — print the command that WOULD be executed to stdout and exit
  with code `0`. Does not spawn any subprocess.
- `--verbose`, `-v` — log adapter selection and the constructed command to
  stderr before executing it.
- `--config-dir <path>` — override the default config root
  (`~/.config/claude-panes`). Both `layouts/` and `config.toml` are resolved
  relative to this path.
- `--help`, `-h` — print help for this subcommand and exit `0`.

#### Examples

```
claude-panes start feature-x
claude-panes start ./my-layout.toml
claude-panes start feature-x --dry-run
claude-panes start feature-x --terminal wezterm
claude-panes start feature-x --config-dir /etc/claude-panes -v
```

#### Exit codes

- `0` — terminal launched. ClaudePanes exits after spawning; the terminal owns
  its lifecycle. Also returned by `--dry-run`.
- `1` — unexpected error (uncaught exception). Stderr contains the traceback
  when `--verbose` is set, otherwise a short message.
- `2` — config not found, or layout file is not valid TOML, or the layout
  fails schema validation.
- `3` — no supported terminal installed, or the terminal named by
  `--terminal` is not installed.
- `4` — adapter execution failed (the spawned subprocess returned a non-zero
  exit code, or the spawn itself raised `OSError`).

### 2.2 `claude-panes list`

#### Synopsis

```
claude-panes list [--config-dir <path>] [--json] [--help | -h]
```

#### Description

Lists every layout discovered in `~/.config/claude-panes/layouts/`. Each
`*.toml` file in that directory is treated as a layout; the file's stem
(filename without extension) is the layout's name.

The description column shows the layout's optional `description = "..."`
field if present. (This field should be added to the layout config schema as
an optional string.) If absent, the description column is empty.

#### Flags

- `--config-dir <path>` — override the default config root.
- `--json` — emit machine-readable JSON to stdout instead of plain text.
- `--help`, `-h` — standard help.

#### Output (plain text)

Two columns separated by whitespace. Column widths are sized to the longest
layout name. Output is sorted by layout name.

```
feature-x        Feature X parallel work
three-worktrees  Three worktrees side-by-side
smoke-test       Single-pane smoke test
```

#### Output (`--json`)

A JSON array of objects, one per layout:

```
[
  {"name": "feature-x",       "path": "/home/u/.config/claude-panes/layouts/feature-x.toml",       "description": "Feature X parallel work"},
  {"name": "three-worktrees", "path": "/home/u/.config/claude-panes/layouts/three-worktrees.toml", "description": "Three worktrees side-by-side"},
  {"name": "smoke-test",      "path": "/home/u/.config/claude-panes/layouts/smoke-test.toml",      "description": "Single-pane smoke test"}
]
```

`description` is `null` if the field is absent. The array is empty when no
layouts are present (still exit `0`).

#### Exit codes

- `0` — listing succeeded, including the empty-list case.
- `2` — layout directory does not exist.

### 2.3 `claude-panes validate`

#### Synopsis

```
claude-panes validate <layout> [--config-dir <path>] [--help | -h]
```

#### Description

Parses the layout file and runs the same schema validation that `start` would
run, but does not select an adapter and does not spawn any subprocess. Useful
in CI, in pre-commit hooks, and for verifying a copy-pasted config.

#### Positional arguments

- `<layout>` — same resolution rules as `start`.

#### Flags

- `--config-dir <path>` — override the default config root.
- `--help`, `-h` — standard help.

#### Output

On success, a single line on stdout:

```
OK: <name>
```

`<name>` is the layout's resolved name (file stem, or full path when the
input was a path).

On failure, a single diagnostic line on stderr. The diagnostic includes the
offending key path and, where the TOML parser provides it, the line number.
Example:

```
ERROR: /home/u/.config/claude-panes/layouts/broken-config.toml
  line 7: unknown field 'splitt' at panes[1] (did you mean 'split'?)
```

On the first validation error, `validate` prints the error to stderr and exits
with code `2`. Multi-error aggregation is not implemented in v0.1.0; users
running `validate` should fix errors one at a time and re-run. A TOML parse
error is reported the same way. (See PROGRESS.md Phase 3 backlog.)

#### Exit codes

- `0` — layout is valid.
- `2` — layout is invalid, missing, or not valid TOML.

### 2.4 `claude-panes detect`

#### Synopsis

```
claude-panes detect [--json] [--help | -h]
```

#### Description

Diagnostic command. Prints which supported terminals are available on the
user's system, in priority order, with the full path to each executable. The
priority order is the same order ClaudePanes uses for auto-detection.

Priority order:

1. `wt` (Windows Terminal)
2. `wezterm`
3. `tmux`
4. `zellij`

#### Flags

- `--json` — machine-readable JSON output.
- `--help`, `-h` — standard help.

#### Output (plain text)

Two columns, fixed names in the priority order above. Missing entries say
`not found`.

```
wt        C:\Program Files\WindowsApps\Microsoft.WindowsTerminal_...\wt.exe
wezterm   not found
tmux      not found
zellij    not found
```

#### Output (`--json`)

```
{
  "wt":      "C:\\Program Files\\WindowsApps\\...\\wt.exe",
  "wezterm": null,
  "tmux":    null,
  "zellij":  null
}
```

Missing entries are `null`. The object's key order matches the priority
order above.

#### Exit codes

- `0` — at least one supported terminal was found.
- `3` — none of the supported terminals are installed.

### 2.5 `claude-panes version`

#### Synopsis

```
claude-panes version [--help | -h]
```

#### Description

Prints the tool version and the Python interpreter version. Two lines, one
per field, on stdout.

#### Output

```
claude-panes 0.1.0
python 3.11.7
```

The tool version is the package version. The interpreter version is
`sys.version.split()[0]`.

#### Exit codes

- `0` — always.

## 3. Global flags

These flags apply to every subcommand. They may appear before or after the
subcommand name on the command line.

- `--help`, `-h` — print help and exit `0`. At the top level, prints the
  top-level help. After a subcommand, prints that subcommand's help.
- `--quiet` — suppress non-error output. Stdout output that is purely
  informational (the dry-run banner, the verbose adapter log, the
  `OK: <name>` line from `validate`) is suppressed. Machine-readable output
  (`--json`, the `dry-run` command itself, `list` and `detect` tables) is NOT
  suppressed: `--quiet` only affects human-oriented prose. Errors on stderr
  are never suppressed.

## 4. Configuration resolution order

Several options can come from more than one place. The effective value is
chosen by walking this list and taking the first source that defines a
value:

1. CLI flag (highest priority).
2. Layout file field (the relevant key inside the `<layout>.toml`).
3. User config (`~/.config/claude-panes/config.toml`, or the file inside
   `--config-dir` when set).
4. Auto-detection (lowest priority). Currently this only applies to the
   `terminal` option.

The `terminal` option is the primary example: `--terminal wezterm` beats a
`terminal = "wt"` line in the layout, which beats a default in the user
config, which beats auto-detection. The same precedence rule applies to any
future option that can be set from more than one source.

`--config-dir` is itself a CLI-only flag and does not participate in this
chain; it changes which files steps 2 and 3 read from.

## 5. Stdout vs stderr

ClaudePanes separates machine-readable output from human-readable logs:

- **Stdout** carries machine-readable output and primary command results.
  This includes `--json` payloads, the `list` table, the `detect` table, the
  `version` lines, the `OK: <name>` line from `validate`, and the command
  string printed by `start --dry-run`.
- **Stderr** carries human-readable logs, warnings, and errors. This
  includes the adapter selection log emitted under `--verbose`, validation
  error diagnostics, "not found" and "not installed" errors, and uncaught
  exception messages.

This split is intentional. Users can pipe `claude-panes list --json | jq ...`
or `claude-panes start feature-x --dry-run | bash` without contamination
from log output.

## 6. Help text style

Help text is rendered by `argparse` with no customization. Every subcommand
exposes its own `--help`/`-h`. The top-level parser uses
`description=` and `epilog=` to mention the config directory and a pointer
to this spec; subcommand parsers do the same for their own surface.

We do not write a custom help renderer.

## 7. NOT in MVP

The following commands and behaviors are explicitly out of scope for the
MVP. They may be revisited later, but the MVP will not ship them and the
implementation should not include placeholders for them.

- `claude-panes stop <name>` — killing a layout is hard without a daemon
  tracking the spawned process tree. Deferred.
- `claude-panes status` — observability of running panes is the host
  terminal's job; ClaudePanes does not retain any state after spawning.
- `claude-panes broadcast <name> "<keys>"` — broadcasting input across panes
  is a possible later feature; not MVP.
- `claude-panes new <name>` — interactive config scaffolding wizard.
  Deferred.
- Auto-reload on config change, layout hot-swap, and named-session
  reattachment are all out of scope.

## 8. Worked examples

### Example 1: First-time use

```
$ claude-panes detect
wt        C:\Program Files\...\wt.exe
wezterm   not found
tmux      not found
zellij    not found

$ claude-panes start feature-x --dry-run
[wt adapter] Would execute:
  wt.exe new-tab --title "Feature X" wsl.exe -d Ubuntu -- bash -lc 'cd ~/work/feature-x && claude' \; split-pane -V ...

$ claude-panes start feature-x
# (Windows Terminal opens with the layout)
```

The user starts by running `detect` to confirm at least one supported
terminal is installed, then uses `--dry-run` to inspect the command that
will be spawned, then runs the real command.

### Example 2: Validation

```
$ claude-panes validate broken-config
ERROR: ~/.config/claude-panes/layouts/broken-config.toml
  line 7: unknown field 'splitt' (did you mean 'split'?)
```

`validate` fails fast on the first error and exits with code `2`. Fix that
error and re-run to surface the next one. Multi-error aggregation is deferred
to Phase 3 (see PROGRESS.md).

### Example 3: Override terminal

```
$ claude-panes start three-worktrees --terminal wezterm
# (WezTerm spawns instead of Windows Terminal)
```

The `--terminal` flag overrides the auto-detection step (and any
`terminal = "..."` line in the layout file or user config), per the
resolution order in section 4.
