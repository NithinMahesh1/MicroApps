# ClaudePanes Configuration Format

ClaudePanes reads a TOML layout file and shells out to whichever terminal
multiplexer is installed (Windows Terminal, WezTerm, tmux, or Zellij) to open
the requested tabs and panes. This document describes the complete TOML schema:
every field, every type, every default, the validation rules that govern them,
and a graded set of worked examples from a single pane up to multi-tab
worktree layouts.

ClaudePanes itself is a zero-dependency single-file Python launcher targeting
Python 3.11+ (stdlib `tomllib` is used to parse layouts). No external packages
are required at runtime, and no schema validator is shipped — validation is
performed by the launcher and surfaced through plain text errors.

## 1. File locations

ClaudePanes uses XDG-style paths on all operating systems, including Windows,
so that the same config tree is portable across machines (a checked-in dotfiles
repo, for example, can be cloned to any host and still resolve correctly).

- **Layouts:** `~/.config/claude-panes/layouts/<name>.toml`
  - One TOML file per named layout. The filename stem (the part before
    `.toml`) is used as the default layout name.
  - Example: `~/.config/claude-panes/layouts/feature-x.toml` defines a layout
    named `feature-x` and is invoked as `claude-panes feature-x`.
- **User defaults:** `~/.config/claude-panes/config.toml` (optional)
  - Sets installation-wide defaults such as the preferred terminal adapter.
    Layout-level settings always override the defaults file.

On Windows, `~` is the user profile directory (`C:\Users\<name>`), so the
layouts live in `C:\Users\<name>\.config\claude-panes\layouts\`. The launcher
creates these directories on first run if they do not already exist.

A future `--config-dir` CLI flag may override the base path so that a
project-local config tree can be used. The MVP uses the fixed paths above and
does not accept overrides.

## 2. Top-level schema

A layout file describes two concepts: layout metadata and a list of panes.
Tabs are an optional grouping layer on top of panes. The high-level shape
is:

```toml
# Layout metadata (all optional)
name = "feature-x"
terminal = "wt"
working_dir = "~/work/feature-x"

# Optional shell prelude prepended to every pane's command
[shell]
prelude = "cd ~/work/feature-x && "

# Either a top-level [[panes]] array (single-tab layout)
# OR a [[tabs]] array (multi-tab layout) — never both.
```

The two layout shapes are mutually exclusive. A file with both top-level
`[[panes]]` and `[[tabs]]` is a validation error. See section 6.

### 2.1 Metadata fields

- `name` — used as the multiplexer session name where supported (tmux,
  zellij). Defaults to the layout filename stem.
- `description` (optional string) — human-readable summary shown in
  `claude-panes list`. Not propagated to the multiplexer; it exists purely
  to help you tell layouts apart in the listing output.
- `terminal` — which adapter to use. If omitted, the launcher auto-detects
  by probing for available executables in PATH order: `wt`, `wezterm`,
  `tmux`, `zellij`.
- `working_dir` — a default working directory for every pane. Pane-level
  `working_dir` overrides this value. The string is expanded with `~` and
  any environment variables before being passed to the multiplexer.

### 2.2 The `[shell]` table

The optional `[shell]` table currently contains a single field, `prelude`,
which is prepended to every pane's `cmd` string before the command is handed
to the multiplexer. The intended use is for repetitive boilerplate such as
`cd`ing to the working directory, activating a virtualenv, or sourcing an
env file:

```toml
[shell]
prelude = "cd ~/work/feature-x && source .venv/bin/activate"
```

The prelude is joined to each pane's `cmd` with ` && ` (a literal
space-ampersand-ampersand-space). The result for a prelude `P` and a pane
command `C` is exactly the string `P && C`. Because `&&` short-circuits in
every supported shell, this means **the pane command only runs if the
prelude succeeds** — if the `cd` fails or the virtualenv activation errors,
the pane command is not executed.

Before/after example. Given:

```toml
[shell]
prelude = "cd ~/work/feature-x"

[[panes]]
cmd = "claude"

[[panes]]
cmd = "git status"
split = "vertical"
```

the two panes are handed to the multiplexer as if they had been written:

```toml
[[panes]]
cmd = "cd ~/work/feature-x && claude"

[[panes]]
cmd = "cd ~/work/feature-x && git status"
split = "vertical"
```

Apart from inserting the ` && ` separator, ClaudePanes does not parse or
quote either side. If your prelude or your `cmd` contains shell
metacharacters that need quoting, you must escape them yourself. Note that
because the join already supplies ` && `, your prelude should **not** end
with its own trailing `&&`. See the security doc for details on the
launcher's quoting model.

Use the prelude sparingly. Explicit per-pane commands are easier to read
and audit, and the prelude becomes painful when one pane needs a different
working directory or shell from the rest.

## 3. Single-tab layouts (panes only)

The simplest layout consists of one tab containing one or more panes. Use a
top-level `[[panes]]` array. The first pane in the array is the **anchor**:
it is opened directly in the new tab. Each subsequent pane describes how to
split off an existing pane (by default the previous one in the array).

```toml
[[panes]]
cmd = "wsl -d Ubuntu-22.04 -- bash -lc 'cd ~/work/feature-x && claude'"
title = "Claude"

[[panes]]
cmd = "wsl -d Ubuntu-22.04 -- bash -lc 'cd ~/work/feature-x && git status'"
split = "vertical"
size = 0.4
title = "Status"

[[panes]]
cmd = "wsl -d Ubuntu-22.04 -- bash -lc 'cd ~/work/feature-x && npm run dev'"
split = "horizontal"
parent = 0
title = "Dev server"
```

Key points:

- The first `[[panes]]` entry has no `split` (it is the anchor and there is
  nothing to split off yet). A `split` value on the first pane is ignored
  with a warning.
- The second `[[panes]]` entry splits the first pane vertically with the
  new pane taking 40% of the parent.
- The third `[[panes]]` entry sets `parent = 0`, which means "split off
  pane index 0 (the anchor)" rather than the default of splitting off the
  previous pane. This lets you build non-linear layouts (see Example C).

`split = "vertical"` means a left/right division (a vertical separator line
between the two panes). `split = "horizontal"` means a top/bottom division
(a horizontal separator line). This matches the convention used by tmux,
WezTerm, and Zellij; Windows Terminal uses the opposite naming internally
and ClaudePanes translates between the two.

## 4. Multi-tab layouts

For layouts with more than one tab, use the `[[tabs]]` array. Each tab has
its own `[[tabs.panes]]` array with exactly the same schema as the top-level
`[[panes]]` array described above.

```toml
[[tabs]]
title = "Feature A"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-a && claude'"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-a && git status'"
split = "vertical"

[[tabs]]
title = "Feature B"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-b && claude'"
```

The first tab is the active tab when the terminal opens. Subsequent tabs
are created in declaration order. Tab indexes are not exposed in the
config — pane `parent` references are always scoped to the panes in the
same tab.

## 5. Field reference

This section is the authoritative type listing for every field in the schema.
Each entry gives the field name, type, required/optional status, default
value, a one-paragraph description, and an inline example.

### 5.1 Top-level fields

#### `name`

- **Type:** string
- **Required:** no
- **Default:** the layout filename stem (e.g. `feature-x` for
  `feature-x.toml`)
- **Description:** Used as the multiplexer session name where the underlying
  tool supports named sessions (currently tmux and Zellij). For Windows
  Terminal and WezTerm this field is informational and shows up in launcher
  log output but is not propagated to the terminal.

```toml
name = "feature-x"
```

#### `description`

- **Type:** string
- **Required:** no
- **Default:** none (no description line printed by `list`)
- **Description:** Human-readable summary of the layout, displayed in the
  second column of `claude-panes list` output. The value is not propagated
  to the multiplexer and has no effect on how panes are opened — it exists
  purely so you can tell several layouts apart at a glance.

```toml
description = "Three-worktree parallel Claude run for the auth refactor"
```

#### `terminal`

- **Type:** string
- **Required:** no
- **Default:** auto-detected by probing PATH in the order `wt`, `wezterm`,
  `tmux`, `zellij`
- **Description:** Which terminal adapter to use. Must be one of the
  supported names: `wt` | `wezterm` | `tmux` | `zellij`. Any other value
  is a validation error. If the named adapter's executable is not on PATH
  the launcher exits with a clear error rather than silently falling back.

```toml
terminal = "wezterm"
```

#### `working_dir`

- **Type:** string
- **Required:** no
- **Default:** the current working directory of the launcher process
- **Description:** Default working directory for all panes in the layout.
  The value is expanded with `~` and `$VAR` / `%VAR%` style environment
  variables before being passed to the multiplexer. A pane-level
  `working_dir` overrides this value for that pane only.

```toml
working_dir = "~/work/feature-x"
```

### 5.2 The `[shell]` table

#### `[shell].prelude`

- **Type:** string
- **Required:** no
- **Default:** `""` (empty string — no prelude is prepended)
- **Description:** A string prepended to every pane's `cmd` before the
  command is handed to the multiplexer. The prelude and the pane `cmd` are
  joined with ` && ` (so for prelude `P` and command `C` the pane runs
  `P && C`, and `C` only executes if `P` succeeds). Apart from inserting
  that separator no parsing or quoting is performed. Typical uses are to
  `cd` to a working directory, activate a virtualenv, or source an env
  file. Do not append your own trailing `&&` — the join supplies it. Use
  sparingly: explicit per-pane commands are easier to audit.

```toml
[shell]
prelude = "cd ~/work/feature-x"
```

### 5.3 The `[[panes]]` array

The same schema applies to both top-level `[[panes]]` and `[[tabs.panes]]`.

#### `panes.cmd`

- **Type:** string
- **Required:** **yes**
- **Default:** none — omitting `cmd` is a validation error
- **Description:** The command to run inside the pane. Quoting is the
  config author's responsibility. ClaudePanes passes the string to the
  multiplexer as-is (after joining `[shell].prelude` in front of it with
  ` && ` if a prelude is set — see section 2.2); the multiplexer is
  responsible for invoking the user's shell. See the security doc for the
  full quoting model.

```toml
cmd = "wsl -- bash -lc 'cd ~/work && claude'"
```

#### `panes.title`

- **Type:** string
- **Required:** no
- **Default:** none — the multiplexer chooses (usually the running command
  name)
- **Description:** A human-readable pane title. Honored by Windows Terminal,
  WezTerm, and tmux. Zellij ignores pane titles in its current versions
  and the field is dropped silently for that adapter.

```toml
title = "Claude"
```

#### `panes.split`

- **Type:** string
- **Required:** no for the first pane in a tab; **yes** for every
  subsequent pane in the same tab
- **Default:** `"vertical"` for panes after the first; ignored on the
  first pane
- **Description:** Direction in which to split the parent pane. One of:
  - `"vertical"` — left/right split (vertical separator between panes)
  - `"horizontal"` — top/bottom split (horizontal separator between panes)
  Any other value is a validation error.

```toml
split = "vertical"
```

#### `panes.size`

- **Type:** float
- **Required:** no
- **Default:** the multiplexer's choice (typically 0.5 — an even split)
- **Description:** Fraction of the parent pane the new pane should occupy
  after the split. Must satisfy `0.0 < size < 1.0`. Values of exactly 0
  or 1, or values outside that range, are validation errors.

```toml
size = 0.4
```

#### `panes.parent`

- **Type:** integer
- **Required:** no
- **Default:** the index of the previous pane in the same tab
- **Description:** Zero-based index into the same tab's `[[panes]]` array.
  The new pane is split off from the referenced parent pane rather than
  the previous pane. Must reference an **earlier** index in the same tab
  (you cannot reference a pane that has not been created yet). Negative
  values, out-of-range values, and forward references are validation
  errors.

```toml
parent = 0
```

#### `panes.working_dir`

- **Type:** string
- **Required:** no
- **Default:** the top-level `working_dir` if set, otherwise the launcher's
  current working directory
- **Description:** Working directory for this pane only. Same expansion
  rules as the top-level `working_dir`. Per-pane overrides win over the
  top-level value.

```toml
working_dir = "~/work/feature-x/server"
```

### 5.4 The `[[tabs]]` array

The `[[tabs]]` array is mutually exclusive with the top-level `[[panes]]`
array — see the validation rules in section 6.

#### `tabs.title`

- **Type:** string
- **Required:** no
- **Default:** none — the multiplexer chooses (usually the first pane's
  title or running command)
- **Description:** Human-readable tab title. Honored by all four adapters.

```toml
title = "Feature A"
```

#### `tabs.panes`

- **Type:** array of pane tables
- **Required:** **yes** — every tab must define at least one pane
- **Default:** none
- **Description:** Same schema as the top-level `[[panes]]` array described
  in 5.3. Pane `parent` indexes are scoped to this tab only and cannot
  refer to panes in other tabs.

```toml
[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work && claude'"
```

## 6. Validation rules

The launcher validates the parsed TOML before invoking any external
process. Validation failures abort with a clear message indicating the
offending field and the rule that was violated. The full rule set is:

- **Exactly one of `[[panes]]` or `[[tabs]]` must be present.** A file with
  both is a validation error. A file with neither is also an error.
- **At least one pane must exist.** For single-tab layouts, the top-level
  `[[panes]]` array must have one or more entries. For multi-tab layouts,
  every `[[tabs]]` entry must have one or more `[[tabs.panes]]` entries.
- **Unknown top-level keys produce a warning, not a fatal error.** This is
  deliberate: it lets users experiment with future fields (see section 8)
  without their layouts breaking. Unknown keys inside `[[panes]]` and
  `[[tabs]]` follow the same rule.
- **`size` must satisfy `0.0 < size < 1.0`.** Endpoints are excluded — a
  pane occupying 0% or 100% of its parent is never useful.
- **`split` is required for every pane after the first in any tab.** The
  first pane has no split because there is nothing to split off yet. A
  `split` value on the first pane is dropped with a warning.
- **`parent` must reference an earlier pane index in the same tab.** Forward
  references and cross-tab references are errors. The first pane (index
  0) cannot have a `parent` value (there is nothing to reference).
- **`terminal`, if specified, must be one of the supported adapter names.**
  Currently: `wt`, `wezterm`, `tmux`, `zellij`. Any other value is an
  error.
- **`cmd` is required on every pane.** A missing or empty `cmd` is an
  error.
- **All string fields are taken literally.** Tilde expansion and
  environment-variable expansion are applied to `working_dir` (top-level
  and per-pane) and nowhere else. `cmd` and `prelude` are otherwise passed
  through unmodified, the one exception being that a non-empty `prelude` is
  joined to each `cmd` with ` && ` (see section 2.2) before the combined
  string reaches the multiplexer.

## 7. Complete worked examples

Each example below is a complete, valid layout file. Save any of them as
`~/.config/claude-panes/layouts/<name>.toml` and invoke with
`claude-panes <name>`.

### Example A: Minimal — one pane

The smallest useful layout: one pane that opens Claude inside WSL.

```toml
[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work && claude'"
```

What it does: opens one new tab in your terminal containing one pane that
runs Claude inside the default WSL distribution.

### Example B: Two panes side-by-side

Claude on the left taking 65% of the width, a live `git status` watch on
the right taking 35%.

```toml
[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && claude'"
title = "Claude"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && watch -n 2 git status'"
split = "vertical"
size = 0.35
title = "Git watch"
```

ASCII layout:

```
+-----------------------------+---------------+
|                             |               |
|                             |               |
|         Claude              |   Git watch   |
|                             |               |
|                             |               |
+-----------------------------+---------------+
```

### Example C: Three panes — Claude on left, status above, server below

The right column is split into two horizontal panes, both children of the
right side. This requires the second pane to set `parent = 0` so that the
third pane can be split off the second.

```toml
[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && claude'"
title = "Claude"

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && git status'"
split = "vertical"
size = 0.4
title = "Status"
parent = 0

[[panes]]
cmd = "wsl -- bash -lc 'cd ~/work/feature-x && npm run dev'"
split = "horizontal"
size = 0.5
parent = 1
title = "Dev"
```

ASCII layout:

```
+---------------------+----------------+
|                     |  Status        |
|                     +----------------+
|     Claude          |                |
|                     |  Dev server    |
|                     |                |
+---------------------+----------------+
```

How to read this:

- Pane 0 (anchor): Claude, full tab.
- Pane 1: splits pane 0 vertically. The right 40% becomes "Status".
- Pane 2: splits pane 1 horizontally. The bottom half of "Status" becomes
  "Dev server".

If you omitted `parent = 1` on the third pane, ClaudePanes would default
to splitting off pane 1 anyway (the previous pane), so the layout would
be identical. The explicit `parent` is shown for clarity.

### Example D: Multi-tab — three worktrees, each with Claude + status

The intended use case for ClaudePanes: running Claude in parallel across
multiple git worktrees, one tab per worktree, each tab with Claude on the
left and a `git status` pane on the right.

```toml
name = "three-worktrees"
terminal = "wt"

[[tabs]]
title = "Auth refactor"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/auth-refactor && claude'"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/auth-refactor && git status'"
split = "vertical"
size = 0.3

[[tabs]]
title = "Payment fix"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/payment-fix && claude'"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/payment-fix && git status'"
split = "vertical"
size = 0.3

[[tabs]]
title = "Migration"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/migration && claude'"

[[tabs.panes]]
cmd = "wsl -- bash -lc 'cd ~/work/migration && git status'"
split = "vertical"
size = 0.3
```

What it does: opens Windows Terminal with three tabs. Each tab has Claude
on the left (70% width) and a `git status` pane on the right (30% width).
Tab titles match the worktree names so you can switch between them by
clicking the tab strip or with `Ctrl+Tab`.

## 8. Future fields (NOT in MVP)

The fields listed below are reserved names that the schema may grow into
in subsequent releases. They are documented here so that the names do not
get used for something else, and so that early adopters know what is on
the roadmap. The MVP launcher will warn (not error) if it sees these keys
in a layout file, as described in the validation rules.

- **`[[panes.env]]`** — per-pane environment variables. Will allow a pane
  to set or override env vars without baking them into the `cmd` string.
- **`broadcast_input`** — synchronize keystrokes across panes. Intended
  for parallel Claude orchestration, where one keystroke in the broadcast
  pane is mirrored to every pane in the broadcast group.
- **`restart_on_exit`** — automatically restart panes whose process exits
  with a non-zero status, similar to a tiny supervisor. Useful for dev
  servers that crash and need to be manually restarted today.

These fields are planned but not implemented in the MVP. Do not write
launcher code that depends on them yet; their final names and semantics
may change based on feedback from the initial release.
