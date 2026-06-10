# ClaudePanes Design Decisions

This document records the architectural decisions made for ClaudePanes, a zero-dependency
single-file Python launcher that reads a TOML layout config and shells out to whichever
terminal multiplexer is installed on the host (Windows Terminal, WezTerm, tmux, Zellij).

Each entry is an Architecture Decision Record (ADR): a short, structured justification
of one choice. ADRs are append-only — supersede rather than rewrite.

---

## ADR-001: Launcher, not a terminal emulator

**Status:** Accepted
**Date:** 2026-05-13

### Context
The user wants a multi-pane Claude Code workflow on Windows 11. Building a real terminal
emulator means solving ConPTY reflow, Unicode grapheme width, IME input, VT escape
parsing, font fallback, and GPU rendering — collectively person-years of work that
mature projects (Windows Terminal, WezTerm) already do well.

### Decision
Build a launcher that delegates all pane mechanics — rendering, input, splitting,
focus — to an existing terminal multiplexer already installed on the user's machine.

### Consequences
- Tool stays small enough to read end-to-end in one sitting.
- Users get the rendering quality of their preferred terminal for free.
- We inherit each terminal's limitations and bugs; we do not control the UX.
- Feature parity across adapters is best-effort, not guaranteed.

### Alternatives considered
- **Build from scratch with ratatui / portable-pty**: rejected — complexity vastly
  exceeds the value; we would be reinventing solved problems.
- **Fork WezTerm**: rejected — maintenance burden of tracking upstream is permanent,
  and WezTerm already exposes a CLI we can drive.

---

## ADR-002: Python 3.11+ as implementation language

**Status:** Accepted
**Date:** 2026-05-13

### Context
The launcher must run cross-platform (Windows primary, macOS/Linux secondary), be easy
to distribute as a single readable file, and be transparent to a security-conscious
user who wants to audit the code before running it.

### Decision
Use Python 3.11 or later. The 3.11 floor is chosen specifically so `tomllib` is
available in the standard library, eliminating any third-party TOML parser.

### Consequences
- Source ships as plain text; users can read every line before executing.
- Python 3.11+ is pre-installed on most modern dev machines and trivial to install where not.
- Older Python versions (3.10 and below) are unsupported; users on LTS distros may need
  a newer interpreter.

### Alternatives considered
- **PowerShell**: rejected — not cross-platform in practice; PowerShell Core works but
  syntax is awkward for the data-shaping this tool does.
- **Go single binary**: rejected — distribution as an opaque binary undermines the
  "audit before running" property; build pipeline is overkill for a script.
- **Rust**: rejected — overkill for a glorified `subprocess.run` wrapper; compile times
  and toolchain cost outweigh any runtime benefit.

---

## ADR-003: Zero third-party dependencies

**Status:** Accepted
**Date:** 2026-05-13

### Context
The user explicitly raised supply-chain security concerns and vets tools for CVE history
and maintenance status before adopting. The tool's job is small: parse a config, probe
for a terminal, spawn it. Pulling in a dependency tree for that is unjustified.

### Decision
Use only the Python standard library. Permitted modules: `tomllib`, `subprocess`,
`argparse`, `shutil`, `pathlib`, `os`, `sys`, and `typing`.

### Consequences
- Audit surface equals the Python stdlib plus our own source file — nothing else.
- No `requirements.txt`, no `pip install`, no lockfile, no Dependabot noise.
- We hand-write things a library would provide (CLI parsing help, config validation
  errors). For a five-field schema this is cheaper than a dependency.

### Alternatives considered
- **`click` for CLI**: rejected — `argparse` is in stdlib and adequate for our flag set.
- **`pydantic` for config validation**: rejected — a five-field schema validates in
  fewer lines than the import statement saves.
- **`rich` for pretty output**: rejected — `print` is sufficient; users running this
  already have a capable terminal handling colors.

---

## ADR-004: TOML for config format

**Status:** Accepted
**Date:** 2026-05-13

### Context
We need a human-editable, declarative config format. Hard requirement: the config must
not be executable code — running arbitrary code from a config file is unacceptable from
both a security and a debuggability standpoint.

### Decision
Use TOML, parsed via the standard library `tomllib` module (Python 3.11+).

### Consequences
- Config is data-only by construction; no code path runs user TOML as Python.
- Comments are supported, which matters for layouts that users tweak by hand.
- We are bound to TOML's expressiveness; deeply nested structures get awkward, but our
  schema is flat enough that this does not bite.

### Alternatives considered
- **JSON**: rejected — no comments, awkward for nested tables, and quoting noise hurts
  readability. Acceptable fallback if a 3.11+ requirement ever becomes a blocker.
- **YAML**: rejected — requires PyYAML (violates ADR-003); `yaml.load` has a CVE history
  for arbitrary object construction, and even `safe_load` is more attack surface than
  needed for our use case.
- **Python file**: rejected — arbitrary code execution from a config file is an
  unacceptable security posture.

---

## ADR-005: Single-file initially

**Status:** Accepted
**Date:** 2026-05-13

### Context
This is an MVP. The user prefers simple, auditable code and dislikes premature
structure. The whole tool is essentially: read TOML, pick adapter, build command,
spawn process.

### Decision
Ship as one Python file (`claude_panes.py` or equivalent) until growth justifies a
split into a package.

### Consequences
- A new contributor or auditor can read the entire tool in roughly fifteen minutes.
- No `__init__.py` shuffling, no relative-import gotchas, no install step.
- When the file grows past roughly 800 lines or the adapter set explodes, a package
  split becomes warranted — not before.

### Alternatives considered
- **Package layout from day one** (`claudepanes/`, `claudepanes/adapters/`, etc.):
  rejected — premature structure adds friction without paying for itself at MVP scale.

---

## ADR-006: Multiple terminal adapters via a Protocol-shaped interface

**Status:** Accepted
**Date:** 2026-05-13

### Context
Each supported terminal has a different CLI shape: `wt.exe` takes a chained command
string with `;` separators, `wezterm cli spawn` takes individual invocations, `tmux`
uses `new-session` / `split-window`, `zellij` uses layout files or `action` subcommands.
We need to keep core logic terminal-agnostic.

### Decision
Define a small uniform adapter interface (typing.Protocol or an ABC) with three methods:
`is_available()`, `build_command(layout)`, and `execute(command)`. One class per
terminal implements it.

### Consequences
- Adding a new terminal is one new class plus one registry entry.
- Core flow (load config, pick adapter, run) is terminal-agnostic and trivially testable
  per-adapter.
- Adapters can drift in capability; the interface caps what the core can rely on.

### Alternatives considered
- **Separate scripts per terminal** (`claude_panes_wt.py`, `claude_panes_tmux.py`):
  rejected — duplicates config loading, argument parsing, and error handling four times.
- **`if/elif` tree on terminal name inside one function**: rejected — readable at two
  branches, unmaintainable at four, and forces every branch to live in one giant
  function.

---

## ADR-007: Auto-detect host terminal with explicit override

**Status:** Accepted
**Date:** 2026-05-13

### Context
A user may have zero, one, or several supported multiplexers installed. We want the
tool to "just work" out of the box but stay deterministic when the user wants a
specific terminal.

### Decision
Probe with `shutil.which` in a documented priority order (`wt`, `wezterm`, `tmux`,
`zellij`) and use the first match. Allow override via `terminal = "..."` in the TOML
config and a `--terminal` CLI flag (CLI wins over config).

### Consequences
- Zero-config invocation works on a fresh machine that has any supported terminal.
- Behavior is reproducible: same machine state yields the same choice every time.
- The priority order is opinionated; users who disagree must override explicitly.

### Alternatives considered
- **Require explicit choice on every run**: rejected — friction for the common case;
  the user is launching panes, not configuring a launcher.
- **Use `$TERM` or `$TERM_PROGRAM`**: rejected — these reflect the current terminal,
  not what is installed, and are unreliable on Windows where many shells set them
  inconsistently.

---

## ADR-008: Delegate /sandbox to WSL2

**Status:** Accepted
**Date:** 2026-05-13

### Context
Claude Code's `/sandbox` mode does not work on native Windows 11. It relies on
bubblewrap (Linux) or Seatbelt (macOS); neither is available natively on Windows.
Users still want sandbox semantics for risky operations.

### Decision
Per-pane commands generally take the form `wsl.exe -d <distro> -- <cmd>`, putting each
Claude Code session inside WSL2 where bubblewrap is available. ClaudePanes itself does
not implement isolation — it shapes the spawn command so users can compose `wsl.exe`
plus whatever Claude Code requires.

### Consequences
- Sandbox semantics work as long as the user has WSL2 plus a distro with bubblewrap.
- ClaudePanes stays out of the security-policy business; we never claim isolation.
- Native-Windows users without WSL2 get a clear failure (`wsl.exe` not found) rather
  than a silent loss of isolation.

### Alternatives considered
- **Windows Sandbox per pane**: rejected — boot time is many seconds, there is no
  programmatic stdio surface, and it is not designed for interactive multi-pane use.
- **Docker container per pane**: rejected as default — too heavy for typical use, adds
  Docker as a hard dependency, and complicates filesystem sharing for git worktrees.
  Can remain an opt-in pattern users compose themselves.

---

## ADR-009: Permission yes-fatigue is out of scope

**Status:** Accepted
**Date:** 2026-05-13

### Context
The user separately raised "yes-fatigue" from Claude Code prompting on read-only
commands (`ls`, `git status`, etc.). Tempting to bundle a fix into this tool, but it
is a Claude Code configuration concern, not a pane-launching concern.

### Decision
Out of scope. The problem is solved by Claude Code's `settings.json` allowlist,
documented separately in `permission-allowlist.md`. ClaudePanes does not write,
modify, or read that file.

### Consequences
- Clean separation of concerns: ClaudePanes launches panes; settings configure Claude.
- Users apply allowlists independently and can reuse them outside ClaudePanes.
- Two artifacts to maintain instead of one, but each is small and orthogonal.

### Alternatives considered
- **Bake an allowlist installer into ClaudePanes**: rejected — scope creep; couples
  two unrelated problems; the user can apply settings independently with a one-line
  copy.

---

## ADR-010: No persistent state, no daemon

**Status:** Accepted
**Date:** 2026-05-13

### Context
A long-running orchestrator would let us track pane lifecycle, restart crashed panes,
and offer IPC between them. It would also add a daemon to install, a socket to
secure, recovery semantics to design, and a lifecycle bug surface to debug.

### Decision
ClaudePanes is fire-and-forget. It reads the config, spawns the configured layout in
the host terminal, and exits. All ongoing state lives in the host terminal — which is
already designed to manage it.

### Consequences
- No daemon, no service, no socket, no autostart entry, no PID file.
- No cross-pane orchestration features; users get whatever the host terminal provides.
- A future long-running variant can be built on top without breaking this one.

### Alternatives considered
- **Long-running orchestrator with IPC**: rejected — scope creep at MVP. Can be added
  later as a separate mode if a concrete need emerges.

---

## ADR-011: `start` is fire-and-forget

**Status:** Accepted
**Date:** 2026-05-20

### Context
Once ClaudePanes spawns the host terminal, the terminal multiplexer owns the lifecycle
of every pane it created. There is no shared process tree we can `wait` on across all
supported adapters: `wt.exe` returns immediately by design, `wezterm cli spawn` returns
the new pane id and exits, `tmux` detaches into the server, and `zellij` execs into its
own session. ADR-010 already commits to no daemon, and cli-spec.md §2.1 already states
that ClaudePanes exits immediately after spawning.

### Decision
`start` is fire-and-forget. After the adapter's spawn command returns, ClaudePanes exits
with code `0` regardless of whether the user has interacted with the resulting panes.

### Consequences
- CI cannot `wait` on a ClaudePanes invocation to know the user's session has ended;
  that is the host terminal's job, not ours.
- A future `--wait` flag is a non-breaking escape hatch if a concrete use case appears
  (e.g. some adapters support a foreground mode).
- Exit-code semantics in cli-spec.md §2.1 only reflect the spawn step, never the user's
  in-pane work.

### Alternatives considered
- **Block until the terminal window closes**: rejected — only works for a subset of
  adapters (not `wt`), and conflicts with ADR-010's no-daemon stance.

---

## ADR-012: Windows Terminal invocation goes through `cmd.exe /c`

**Status:** Accepted
**Date:** 2026-05-20

### Context
`wt.exe` uses `;` as the action-chain separator (e.g. `wt new-tab ; split-pane`).
PowerShell — Windows 11's default shell — intercepts `;` as a statement separator and
mangles the chain before `wt` ever sees it. Even when ClaudePanes uses `subprocess.run`
with a list-argv (which on Windows builds the command line directly without invoking
PowerShell), users who copy-paste the dry-run output into a PowerShell prompt hit the
same trap.

### Decision
Always prefix the `wt.exe` argv with `["cmd.exe", "/c"]`. `cmd.exe` does not interpret
`;`, so the action chain reaches `wt.exe` intact regardless of how the user pastes or
re-invokes the printed command.

### Consequences
- Requires `cmd.exe` on PATH. This is universal on Windows; no user config burden.
- Belt-and-suspenders: works whether the caller is PowerShell, `cmd.exe`, or
  `subprocess.run` direct.
- No knob is exposed — the wrapper is unconditional for the wt adapter. Users who
  dislike it can use a different adapter (`--terminal wezterm` etc.).

### Alternatives considered
- **Rely on list-argv to bypass PowerShell**: rejected — works for `subprocess.run`
  but breaks the dry-run-as-copy-paste-recipe story.
- **Expose a `--no-cmd-wrapper` flag**: rejected — YAGNI; nobody has asked for it and
  the wrapper costs nothing.

---

## ADR-013: tmux on Windows is invoked from inside WSL by the user

**Status:** Accepted
**Date:** 2026-05-20

### Context
tmux is a POSIX tool with no native Windows port. On a Windows host it runs inside WSL2.
ADR-008 establishes that the WSL boundary lives in the user's per-pane `cmd` (e.g.
`wsl.exe -d Ubuntu -- claude`), not in ClaudePanes. Auto-wrapping tmux calls with
`wsl.exe` would force ClaudePanes to choose a distro name and login behavior on the
user's behalf — exactly the policy decisions ADR-008 says we don't make.

### Decision
On Windows, ClaudePanes does not auto-wrap tmux invocations with `wsl.exe`. Users who
want to use the tmux adapter on a Windows machine must invoke ClaudePanes from inside a
WSL session (where `tmux` is on PATH and the adapter detects normally).

### Consequences
- `detect` on native Windows will not list tmux — that's the correct signal: tmux is
  genuinely not available in that environment from ClaudePanes' point of view.
- ClaudePanes stays out of the distro-selection and login-shell-policy business.
- Documentation (README, terminal-adapters.md) calls this out so the absence of tmux
  from `detect` on Windows is not surprising.

### Alternatives considered
- **Auto-wrap with `wsl.exe -- tmux ...`**: rejected — requires guessing distro name
  and shell-init behavior; conflicts with ADR-008.
- **Add a `--via-wsl <distro>` flag**: rejected — premature; can be added later if
  users ask for it without breaking anything.
