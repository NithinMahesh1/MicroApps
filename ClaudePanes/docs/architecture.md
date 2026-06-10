# ClaudePanes — Architecture

## 1. Overview

ClaudePanes is a zero-dependency, single-file Python launcher (Python 3.11+, stdlib only) that translates a declarative TOML layout into invocations of an already-installed terminal multiplexer. Its sole job is to read a layout description, pick a host terminal (Windows Terminal, WezTerm, tmux, or Zellij), and shell out the right CLI calls to open tabs and pre-split panes running pre-configured commands. The primary use case is launching parallel Claude Code sessions across git worktrees on Windows 11, with each pane running inside WSL2 to access `/sandbox`. ClaudePanes itself owns no pane mechanics, no PTY, no UI — the host terminal does all the heavy lifting.

## 2. High-level diagram

```
                 User invocation (CLI)
                          |
                          v
                +---------+---------+
                |  Argument parser  |
                |   (main, argv)    |
                +---------+---------+
                          |
                          v
                +---------+---------+
                |   Config loader   |
                | tomllib + schema  |
                |    validation     |
                +---------+---------+
                          |
                          v
                +---------+---------+
                |   Layout model    |
                | (tabs / panes /   |
                |  splits / cmds)   |
                +---------+---------+
                          |
                          v
                +---------+---------+
                | Terminal detector |
                | shutil.which:     |
                | wt, wezterm,      |
                | tmux, zellij      |
                +---------+---------+
                          |
                          v
                +---------+---------+
                | Adapter selector  |
                | (1-of-N strategy) |
                +---------+---------+
                          |
                          v
       +------------------+------------------+
       | Adapter: translates Layout into     |
       | host-terminal-specific argv         |
       | (see terminal-adapters.md)          |
       +------------------+------------------+
                          |
                          v
                +---------+---------+
                |     Executor      |
                |  subprocess.run   |
                | (quoting, exit    |
                |   code surface)   |
                +-------------------+
```

The flow is strictly top-down. There is no feedback loop, no daemon, no IPC back to ClaudePanes after the terminal is launched.

## 3. Components

### 3.1 CLI entry point (`main()`)

The single entry point. Parses `sys.argv` with `argparse`, dispatches to one of a small set of subcommands (`start`, `list`, `validate`, `detect`, `version`). It owns argv parsing and top-level exit-code mapping only. No file I/O, no subprocess calls, no business logic here — those belong to the loader, detector, and executor. Errors bubble up as typed exceptions and are converted into human-readable messages plus an exit code at this layer.

### 3.2 Config loader

Reads a TOML file via stdlib `tomllib` (Python 3.11+ built-in). Resolves the config path: explicit path argument, then `~/.config/claude-panes/layouts/<name>.toml`, then a `--config-dir` override. Validates required fields (tab name, pane command, at least one pane per tab) and raises descriptive errors that include the offending key path (e.g. `tabs[0].panes[2].cmd is required`). The loader produces a validated `Layout` and nothing else — it does not touch terminals or processes. Schema details live in `config-format.md`.

### 3.3 Layout model

A small set of frozen dataclasses representing the parsed config: `Layout`, `Tab`, `Pane`. Pure in-memory data. Immutable by convention (new instances rather than mutation, in line with the project's immutability rule). The model is the contract between the loader and every adapter — adapters depend only on these types, never on raw TOML dicts. The model has no methods that execute anything; it is data, not behavior.

### 3.4 Terminal detector

Probes for installed terminals using `shutil.which` in a defined priority order (configurable, defaulting to `wt`, `wezterm`, `tmux`, `zellij`). Returns the first hit, or honors an explicit override from the config (`terminal = "wezterm"`) or a CLI flag (`--terminal wezterm`). If nothing is found and no override is given, the detector raises a clear error listing what it probed for. Detection is cheap and stateless — re-run on every invocation.

### 3.5 Adapters (one per terminal)

A plug-in family implementing a small protocol. Each adapter encapsulates everything specific to one host terminal:

- `WindowsTerminalAdapter` — emits `wt.exe new-tab ... ; split-pane ...` command strings.
- `WezTermAdapter` — emits `wezterm cli spawn` / `split-pane` invocations, threading pane IDs across calls.
- `TmuxAdapter` — emits `tmux new-session` / `split-window` sequences.
- `ZellijAdapter` — emits a KDL layout file then invokes `zellij --layout <file>`.

Each adapter is self-contained, with no knowledge of any other adapter. Adapters consume a `Layout` and return argv (or a shell command string when the host terminal requires `;`-chained syntax, as Windows Terminal does). The actual command construction for each host lives in `terminal-adapters.md`; this doc only fixes the boundary.

### 3.6 Executor

Builds the final invocation from an adapter's output and runs it via `subprocess.run`. Owns quoting decisions (`subprocess.list2cmdline` on Windows, POSIX rules elsewhere), captures stdout/stderr when useful, and translates the host terminal's exit code into ClaudePanes's own exit code. The executor does not interpret the layout — it just runs what the adapter built. This is the only component that talks to the OS process table.

## 4. Data flow

A typical invocation `claude-panes start feature-x`:

1. `main()` parses argv, sees subcommand `start` with positional arg `feature-x`.
2. Config loader resolves `feature-x` to a TOML path (e.g. `~/.config/claude-panes/layouts/feature-x.toml`), opens it with `tomllib.load`, and validates the schema.
3. Loader returns a `Layout` dataclass tree: e.g. one tab with three vertical splits, each pane running `wsl -d Ubuntu -- bash -lc 'cd ~/work/feature-x && claude'`.
4. Terminal detector runs `shutil.which("wt")`, finds it, returns `WindowsTerminalAdapter`.
5. Adapter walks the `Layout` and builds the `wt.exe new-tab --title "Feature X" wsl ... ; split-pane -V wsl ... ; split-pane -H wsl ...` command.
6. Executor calls `subprocess.run([...])` with the right argv shape for the platform.
7. Windows Terminal opens the tab with the requested panes; each pane starts its configured command.
8. ClaudePanes exits with `0` on successful launch (it does not wait on the panes themselves).

## 5. Adapter interface (sketch)

```python
from typing import Protocol


class Adapter(Protocol):
    name: str  # "wt" | "wezterm" | "tmux" | "zellij"

    def is_available(self) -> bool:
        """True if this terminal is installed and usable."""
        ...

    def build_command(self, layout: Layout) -> list[str]:
        """Translate a Layout into argv for subprocess.run.

        Returns a fully-quoted argv list. For terminals that require
        a single shell-style chained command (e.g. Windows Terminal's
        ';' separator), the chain is encoded as one argv element.
        """
        ...

    def execute(self, layout: Layout, dry_run: bool = False) -> int:
        """Build and run. Returns the host terminal's exit code.

        Default implementation: subprocess.run(self.build_command(layout)).
        Adapters may override execute() if they need multi-step process
        handling (e.g. WezTerm threading pane IDs across calls).
        """
        ...
```

Concrete adapters are picked at runtime by the detector. Adding a new terminal is a matter of dropping in another class implementing this protocol — no changes to the loader, the model, or the executor.

## 6. What we deliberately do NOT do

- No PTY hosting. The host terminal owns the PTY.
- No terminal emulation. We do not render characters; we do not parse ANSI.
- No persistent state. No daemon, no state file, no lock file, no cache.
- No network calls. Ever. Not for telemetry, not for updates.
- No third-party dependencies. Stdlib only, single file, Python 3.11+.
- No code execution from config. TOML is data; we never `eval`, `exec`, or import anything named in a config.
- No process supervision after launch. We are a launcher, not a runner — once `subprocess.run` returns, we are done.
- No GUI, no TUI, no curses, no interactive prompts.

## 7. Future evolution

The current shape is a one-shot CLI, but the seams are deliberately placed to allow growth without disturbing the config format or the adapter pattern. A future TUI dashboard or GUI would sit *above* `main()` as a new front-end that produces the same `Layout` objects and calls the same adapters; the loader, model, detector, adapter protocol, and executor stay untouched. The Command/Event-style boundary between "describe what to launch" (Layout) and "actually launch it" (Adapter.execute) is the single contract — anything that can produce a `Layout` can drive the system, whether that is a TOML file today or a richer interactive UI tomorrow.

## 8. Open questions

- Should `start` block on the terminal process, or fire-and-forget once panes are launched? Implications for exit-code propagation and CI use.
- Should we support broadcasting input (e.g. a synced "type this in every pane" mode), or is that strictly the host terminal's job?
- How do we surface a failed pane (command exits non-zero immediately) back to the user, given that we have no post-launch visibility into the terminal?
- Should the detector's priority order be hardcoded, or driven entirely by config? Trade-off: predictability vs. flexibility.
- For Windows + WSL, do we standardize on `wsl -d <distro> -- bash -lc '...'` as a built-in command wrapper, or keep the config fully literal and push that boilerplate to the user?
