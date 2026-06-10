# Changelog

All notable changes to ClaudePanes will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] - v0.1.0

First public cut of ClaudePanes: a single-file, zero-runtime-dependency Python
CLI that reads a declarative TOML layout and launches a multi-pane Claude Code
session (or any command set) in the host terminal multiplexer.

### Added

#### CLI (`claude_panes.py`)

- Single-file Python 3.11+ launcher (`claude_panes.py`), standard library only.
- `argparse`-based subcommands:
  - `start <layout> [--terminal NAME] [--dry-run] [--verbose] [--config-dir DIR]` — resolve a layout and launch it in the host terminal.
  - `list [--config-dir DIR] [--json]` — enumerate layouts under the config root (`~/.config/claude-panes/layouts/` by default).
  - `validate <layout> [--config-dir DIR]` — parse and schema-check a layout without executing.
  - `detect [--json]` — report which supported terminals are installed and where.
  - `version` — print the tool version and the running Python version.
- Global `--quiet` flag.
- Distinct exit codes per failure class: `0` ok, `1` unexpected, `2` config error, `3` no terminal found, `4` adapter execution error.

#### Terminal adapters

- **Windows Terminal** (`WindowsTerminalAdapter`) — invoked via `cmd.exe /c wt.exe ...` so the `;` sub-command separator survives any host shell. Supports `new-tab` / `split-pane`, `--title`, `--startingDirectory`, vertical (`-V`) and horizontal (`-H`) splits, and `-s <fraction>` for pane sizing.
- **WezTerm** (`WezTermAdapter`) — multi-step execution via `wezterm cli spawn` / `wezterm cli split-pane`, threading the captured `--pane-id` of each pane into the next split. Supports `--new-window` for the first tab, `--cwd`, `--right` / `--bottom` direction, and `--percent` sizing.
- **tmux** (`TmuxAdapter`) — emits a single chained `tmux new-session ... ; split-window ... ; new-window ... ; attach` argv with `-s` session, `-n` window names, `-c` working dirs, `-h` / `-v` splits, and `-p` percentage sizing.
- **Zellij** (`ZellijAdapter`) — renders a KDL layout file to a temp directory and invokes `zellij --layout <path>`; cleans up the temp file on exit. Handles single-pane tabs and uniform `split_direction` per tab.

#### Configuration

- TOML layout format parsed with the standard library `tomllib`.
- Frozen `@dataclass` models (`Pane`, `Tab`, `Layout`) enforcing immutability throughout the pipeline.
- Top-level keys: `name`, `description`, `terminal`, `working_dir`, `[shell] prelude`, and either `[[panes]]` (single-tab shorthand) or `[[tabs]]` (multi-tab form).
- Per-pane fields: `cmd` (required), `title`, `split` (`vertical` | `horizontal`), `size` (strictly between 0 and 1), `parent` (must reference an earlier index), `working_dir`.
- `shell.prelude` is joined to the front of every pane's `cmd` with ` && ` (the pane command runs only if the prelude succeeds), used for `cd $worktree`-style boilerplate.
- Layout argument resolution: bare names look up `~/.config/claude-panes/layouts/<name>.toml`; anything with a path separator or `.toml` suffix is treated as a file path.
- Tilde / `$VAR` expansion in `working_dir` values.

#### Adapter selection

- Auto-detection via `shutil.which` over the priority list `wt -> wezterm -> tmux -> zellij`.
- Override via TOML `terminal = "..."` or CLI `--terminal` (CLI wins).
- `detect` surfaces the resolved binary path for each supported terminal.

#### Tooling and developer experience

- `--dry-run` on `start` prints the command(s) each adapter would invoke (and the rendered KDL for Zellij) without executing — exercised by every adapter.
- Verbose mode (`-v` / `--verbose`) logs the selected adapter and resolved layout path to stderr.
- Each pane's `cmd` is treated as an opaque shell string: it is passed as a single argv element to a host shell (`cmd.exe /c` on Windows; `$SHELL -lc`, falling back to `/bin/sh -c`, on POSIX) so quotes, `&&`, and pipes are honored by the shell rather than re-parsed by the launcher.

#### Tests

- Standard-library `unittest` test suite (no third-party runner), 89 tests:
  - `tests/test_config.py` — TOML parsing, schema validation, error paths.
  - `tests/test_adapters.py` — argv construction for each adapter, dry-run output, KDL rendering.
  - `tests/test_main.py` / `tests/test_detect.py` — `main()` exit-code mapping and `detect_terminal` precedence/override.
  - `tests/test_adapter_flags.py` / `tests/test_validation.py` — per-adapter `size`/`working_dir` emission and type-mismatch `ConfigError`s.
  - `tests/test_prelude_and_shell.py` / `tests/test_kdl_escape.py` — prelude join, cross-platform shell wrapping, and KDL escape / injection-resistance.
- 17 TOML fixtures under `tests/fixtures/` covering minimal, multi-pane, multi-tab, shell-prelude, terminal-override, type-mismatch, and rejection cases (missing `cmd`, bad `size`, unknown field, mutually exclusive `[[panes]]`/`[[tabs]]`).

#### Examples

- 8 ready-to-run layouts under `examples/`:
  - `solo-claude.toml` — single Claude pane.
  - `claude-with-git-watch.toml` — Claude + live `git status` sidecar.
  - `three-worktrees.toml` — parallel Claude sessions across three git worktrees.
  - `ide-layout.toml` — editor + Claude + shell IDE arrangement.
  - `native-windows.toml` — Windows Terminal-targeted layout.
  - `cross-platform.toml` — adapter-agnostic baseline.
  - `with-env-vars.toml` — `$VAR` expansion in `working_dir`.
  - `parent-pane-tree.toml` — non-linear split tree via `parent`.

#### CI and distribution

- GitHub Actions workflow (`.github/workflows/ci.yml`):
  - Test matrix: Python 3.11 / 3.12 / 3.13 on Ubuntu, Windows, and macOS (9 cells, `fail-fast: false`).
  - Lint job: `ruff check` and `ruff format --check` on Ubuntu / Python 3.13, non-blocking (`continue-on-error: true`).
  - Least-privilege `permissions: contents: read` and a `concurrency` group that cancels superseded runs.
  - No install step — stdlib-only project, no `requirements.txt`.
- Release workflow (`.github/workflows/release.yml`): on a `v*.*.*` tag, runs the test suite as a gate, then publishes a GitHub Release attaching `claude_panes.py` and its `.sha256` checksum.
- `install.ps1` — Windows / PowerShell installer.
- `install.sh` — macOS / Linux installer.
- MIT `LICENSE`.

#### Documentation

- `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, plus 15 guides under `docs/`:
  - `architecture.md`, `design-decisions.md` (ADRs), `security.md`,
  - `cli-spec.md`, `config-format.md`, `terminal-adapters.md`,
  - `usage-examples.md`, `permission-allowlist.md`, `development-guide.md`,
  - `related-claude-features.md` (relationship to Anthropic's `claude agents` / `--bg`),
  - `installation.md`, `troubleshooting.md`, `faq.md`, `migration-guide.md`, `code-walkthrough.md`.
- `PROGRESS.md` — phased roadmap and append-only work log.

### Security

- Zero third-party runtime dependencies — only the Python standard library is imported (`argparse`, `json`, `os`, `shutil`, `subprocess`, `sys`, `tempfile`, `tomllib`, `dataclasses`, `pathlib`, `typing`).
- All adapter commands are dispatched via `subprocess.run` with explicit `argv` lists rather than `shell=True`, so user-supplied `cmd` strings cannot inject extra shell commands at the launcher boundary.
- Each pane's `cmd` is handed to the terminal multiplexer as a single opaque argv element and is only ever parsed by the host shell the launcher wraps it in — matching the documented "the multiplexer does what your shell would do" contract in `docs/security.md`. The launcher never splits or re-quotes `cmd`.
- KDL emission for Zellij escapes embedded `\`, `"`, newline, carriage-return, and tab characters in pane titles and command strings, preventing layout-file node injection.
- Generated Zellij KDL files are written inside a `tempfile.TemporaryDirectory()` (mode `0o700` on POSIX) and removed via its context manager even if launch raises.
- Reviewed with `bandit` plus a manual audit (2026-05-22): no `shell=True`, `eval`, `exec`, `os.system`, hardcoded secrets, or untrusted-input injection paths found.
- Sandbox enforcement is explicitly delegated to Claude Code's own `/sandbox` (and WSL on Windows); ClaudePanes does not attempt to confine spawned commands.

### Known limitations

- WezTerm adapter uses multi-step execution; if a mid-layout `split-pane` call fails the earlier panes remain open (no rollback).
- Zellij adapter uses a single `split_direction` per tab; non-uniform pane trees within one tab are not yet supported.
- Zellij adapter does not yet emit a pane's `working_dir` (the `cwd` is silently dropped), and its KDL `command` head is hardcoded to `bash` rather than honoring `$SHELL`.
- `start --dry-run --terminal NAME` still requires NAME's binary to be installed; previewing the command for an absent terminal is not yet supported.
- `claude-panes new <name>` scaffolding, per-pane env overrides, and `list --json` polish are tracked for a future release.
- Running `tmux` from a native Windows shell requires the user to invoke ClaudePanes from inside WSL; auto-wrapping with `wsl.exe` is an open question.

<!-- TODO: Replace [GITHUB URL PENDING] with the actual repo URL once the repository is published. -->
[Unreleased]: [GITHUB URL PENDING]/compare/...HEAD
