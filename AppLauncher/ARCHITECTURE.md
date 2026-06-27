# MicroApps Launcher — Architecture & Module Contracts

This document is the **integration contract**. Each module is implemented by a
separate agent; everyone codes against the signatures below so the pieces fit.

## Package layout
```
AppLauncher/
  launcher.py              # entry point (lazy-imports tui; --check is headless)
  launcher.bat             # `python launcher.py %*`
  requirements.txt         # textual, rich, pyfiglet
  microapps_launcher/
    __init__.py
    models.py              # DONE (contract): Registry, App, Launch (+ ArgPicker), Prepare, Prerequisite
    paths.py               # repo-root + path/command resolution
    manifest.py            # load + validate apps.json -> Registry
    prerequisites.py       # detect runtimes; PrereqResult
    process_manager.py     # spawn/track/stop per launchMode; accepts extra_args
    terminal.py            # POSIX: open a console app in its own terminal window
    prepare.py             # build-once sentinel + run prepare
    arg_picker.py          # discover file choices for argPicker (glob → ArgChoice list)
    config/
      __init__.py
      descriptors.py       # FieldDescriptor + infer from *.example.json
      io.py                # load/save config values (git-ignored real file)
      validation.py        # per-field validation
    tui/
      __init__.py
      app.py               # MicroAppsLauncher(App)
      app_list.py          # AppListScreen (pushes ArgPickerScreen when argPicker set)
      arg_picker_screen.py # ArgPickerScreen modal (OptionList → chosen file path)
      config_screen.py     # ConfigScreen
      widgets.py           # StatusBadge, SecretInput, StringListEditor
      app.tcss             # styling
  tests/                   # pytest; one module per engine file + integration
```

## Hard rules
- **Python 3.11+**, PEP 8, **type annotations on every signature**, `from __future__ import annotations` at the top of every module.
- **Immutability:** never mutate inputs; return new objects. Models are frozen dataclasses.
- **Engine modules** (`paths`, `manifest`, `prerequisites`, `process_manager`, `terminal`, `prepare`, `config/*`) **must NOT import `textual`** — stdlib only (`manifest.py` may *optionally* use `jsonschema` with a stdlib fallback). This keeps `--check` runnable without the TUI deps.
- All manifest paths are **relative + forward-slash**; resolve via `pathlib` then `.resolve()`.
- Files ≤ 400 lines. Add a module docstring.

## Path-resolution contract (implemented in `paths.py`, used everywhere)
- `find_repo_root(start: Path | None = None) -> Path` — walk up from `start` (default: this file's dir) to the first dir containing **both** `apps.json` and `.git`. Raise `FileNotFoundError` if none.
- `resolve_repo(root: Path, rel: str) -> Path` — `(root / rel.replace("\\", "/")).resolve()`. Used for `config_file`, `config_template`, `config_schema`, `docs`.
- `resolve_cwd(root: Path, app: App) -> Path` — `resolve_repo(root, app.cwd)`.
- `resolve_in_cwd(root: Path, app: App, rel: str) -> Path` — resolve `rel` against the app's cwd. Used for `launch.cmd[0]` (when it's a path) and `prepare.sentinel`.
- `resolve_command(root: Path, app: App, cmd: Sequence[str]) -> list[str]` — return a new argv:
  - if `cmd[0] == "python"` -> replace with `sys.executable`.
  - if `cmd[0] == "pip"` -> replace with `[sys.executable, "-m", "pip"]` (splice).
  - else if `cmd[0]` contains `/`, `\`, or ends with `.exe` -> replace with `str(resolve_in_cwd(root, app, cmd[0]))`.
  - else leave as-is (PATH lookup, e.g. `dotnet`).
  - remaining args unchanged.

## `models.py` — `Launch` and `ArgPicker`
- `@dataclass(frozen=True) class ArgPicker: label: str; glob: str` — parsed from the optional `launch.argPicker` manifest object.
- `Launch` has an `arg_picker: ArgPicker | None` field (default `None`). When present, the TUI shows a file-selection prompt before launch; the chosen path is appended to the spawn argv as an extra argument.

## `manifest.py`
- `class ManifestError(Exception)`.
- `load_registry(root: Path) -> Registry` — read `root/"apps.json"`, JSON-parse, validate, return `Registry.from_dict(data)`. Wrap failures in `ManifestError`.
- `validate(data: dict, schema: dict) -> list[str]` — return human-readable errors (empty = valid). Try `import jsonschema` (use `Draft202012Validator`, collect `.iter_errors`); if unavailable, a **minimal** fallback that checks: top-level `version`/`apps`; per app the required keys, `launchMode`/`stack` enums, and the `fire-and-forget => stoppable is false` invariant.
- `load_schema(root: Path) -> dict` — read `root/"apps.schema.json"`.
- `load_registry` must raise `ManifestError` if `validate` returns errors (join them).

## `prerequisites.py`
- `@dataclass(frozen=True) class PrereqResult: ok: bool; label: str; detail: str; fix_hint: str | None = None`
- `check(p: Prerequisite) -> PrereqResult` — dispatch on `p.type`:
  - `python` — find `python`/`python3` via `shutil.which`, run `--version`, parse, compare `>= min_version`. fix_hint: install URL.
  - `node` — `node --version`.
  - `dotnet-sdk` — `dotnet --list-sdks`, pass if any line's version `>= min_version`. fix_hint: "Install .NET 10 SDK from https://dot.net".
  - `binary` — `shutil.which(p.name)`.
  - `binary-any` — pass if any of `p.names` resolves via `shutil.which`; detail lists which are present. fix_hint names the options.
  - `os` — compare `platform.system()` to `p.name` (case-insensitive); if `min_version`, compare `platform.version()`/build `>= min_version` best-effort.
- `check_all(app: App) -> list[PrereqResult]`.
- `parse_version(s: str) -> tuple[int, ...]` and `version_ge(a: str, b: str) -> bool` helpers (lenient: ignore non-numeric suffixes).
- Never raise; a failed probe returns `ok=False` with a helpful `detail`.

## `arg_picker.py`
- `@dataclass(frozen=True) class ArgChoice: value: str; label: str; description: str` — `value` is a cwd-relative POSIX path appended verbatim to the launch argv; `label` is the filename stem; `description` is a best-effort top-level summary (for `.toml` files: the first string scalar found; tolerant, never raises).
- `discover_choices(root: Path, app: App) -> list[ArgChoice]` — expands `app.launch.arg_picker.glob` under `resolve_cwd(root, app)` using `pathlib.Path.glob`; returns each match as an `ArgChoice` with `value` = the file's path relative to the app cwd in POSIX notation. Returns `[]` if the glob matches nothing.
- Pure stdlib; **never imports textual**. Engine modules may call this safely.

**ClaudePanes / relative-path rationale:** `claude_panes.py start <layout>` treats any argument containing `/`, `\`, or ending in `.toml` as a file path resolved against the **process cwd**. The launcher spawns ClaudePanes with `cwd = <repo>/ClaudePanes/`, so passing `examples/solo-claude.toml` (a cwd-relative path) resolves correctly to `<repo>/ClaudePanes/examples/solo-claude.toml`. This is preferred over calling `claude-panes list --json` because that command only scans `~/.config/claude-panes/layouts/`, which does not contain the repo's shipped `examples/*.toml` files and does not exist on a fresh clone.

## `process_manager.py`
- `class ProcessManager:` holds `self._procs: dict[str, subprocess.Popen]`.
  - `launch(self, root: Path, app: App, extra_args: Sequence[str] = ()) -> None` — build argv via `paths.resolve_command`; append `extra_args` after the resolved command; spawn with `cwd=resolve_cwd(...)`. Dispatches on the host OS:
    - **Windows** (`_spawn_windows`): creation flags by `app.launch_mode` — `console` -> `CREATE_NEW_CONSOLE`; `gui` -> `0`; `fire-and-forget` -> `DETACHED_PROCESS | CREATE_NO_WINDOW`. Uses `getattr(subprocess, "CREATE_NEW_CONSOLE", 0)` etc. so the module imports on non-Windows.
    - **POSIX** (`_spawn_posix`): a `console` app is wrapped via `terminal.wrap(cwd, argv)` so it runs in its **own terminal-emulator window** — otherwise it would share (and corrupt) the launcher's TTY, garbling the display and crashing the input thread with `OSError: [Errno 5]` on quit. `gui`/`fire-and-forget` run the command directly. Every POSIX spawn uses `start_new_session=True` and redirects std streams to `DEVNULL` (detaches from the launcher's controlling terminal and keeps stray output from corrupting the Textual display; an app inside a terminal window gets that window's PTY).
    - Track the handle under `app.id` unless `fire-and-forget`.
  - `status(self, app_id: str) -> str` — `"running"` if a stored handle has `poll() is None`, else `"stopped"`.
  - `stop(self, app_id: str) -> None` — if tracked and alive, `_terminate`; drop the handle. No-op if untracked.
  - `_terminate(proc)` — Windows: `terminate()`, wait ~3s, then `kill()`. POSIX: `os.killpg` the child's session with `SIGTERM`, wait ~3s, then `SIGKILL`, so a terminal-launched app dies together with its window.
  - `is_running(self, app_id: str) -> bool`.
- Pure stdlib (`subprocess`, `sys`, `os`, `signal`) + the sibling `terminal` module. Must import cleanly on any OS (platform-specific calls are guarded).

## `terminal.py`
- POSIX helper that opens a command in a **new terminal-emulator window** (Windows uses `CREATE_NEW_CONSOLE` instead). Pure stdlib; never imports `textual`.
- `class TerminalNotFound(OSError)` — raised when no terminal is available; subclasses `OSError` so existing `except OSError` launch handling surfaces it with a helpful message.
- `wrap(cwd: str, argv: Sequence[str]) -> list[str]` — the full argv that runs `argv` in a new window under `cwd`. Honors `$TERMINAL`, else the first available of a priority list (`ptyxis`, `gnome-terminal`, `kgx`, `konsole`, `xfce4-terminal`, `tilix`, `kitty`, `alacritty`, `foot`, `wezterm`, `terminator`, `x-terminal-emulator`, `xterm`). Each invocation is chosen so the spawned process **stays in the foreground** for the window's lifetime (e.g. `ptyxis --standalone`, `gnome-terminal --wait`, `konsole --nofork`), so `poll()`/`terminate()` tracking keeps working. macOS falls back to `osascript` + `Terminal.app` (best-effort, untracked).
- `chosen_terminal() -> str | None` — the terminal `wrap` would use (diagnostics).

## `prepare.py`
- `needs_prepare(root: Path, app: App) -> bool` — `False` if `app.prepare is None`; `True` if no `sentinel`; else `not resolve_in_cwd(root, app, sentinel).exists()`.
- `run_prepare(root: Path, app: App, on_line: Callable[[str], None] | None = None) -> int` — if `not needs_prepare` return `0`; else run `resolve_command(root, app, app.prepare.cmd)` with `cwd=resolve_cwd(...)`, stream stdout+stderr line-by-line to `on_line`, return exit code. Use `Popen(..., stdout=PIPE, stderr=STDOUT, text=True)` and iterate `proc.stdout`.

## `config/descriptors.py`
- `@dataclass(frozen=True) class FieldDescriptor: key: str; label: str; type: str; secret: bool = False; required: bool = False; help: str = ""; placeholder: str = ""` where `type` in `{"text","secret","string-list","file-path","readonly"}`.
- `descriptors_for(app: App, example: dict) -> list[FieldDescriptor]` — infer from the example JSON shape (dot-paths for nested objects like `installed.client_id`); arrays of strings -> `string-list`; keys containing `secret`/`token`/`password`/`key` -> `secret`. Apply per-app overrides for the two known configs (credentials.json: `installed.client_id`/`installed.client_secret` required, client_secret secret; meeting-notes-overlay.json: `notesDirectories` string-list required). `label` = humanized last path segment.
- `flatten(data: dict) -> dict[str, object]` and `unflatten(flat: dict[str, object]) -> dict` (dot-path <-> nested) helpers, exported for `io.py`.

## `config/io.py`
- `load_values(root: Path, app: App) -> dict` — read `app.config_file` if present; else seed from `app.config_template`; strip placeholder sentinels (values matching `^YOUR_` / `^your-` become `""`). Return the **nested** dict.
- `save_values(root: Path, app: App, values: dict) -> Path` — write `values` to `resolve_repo(root, app.config_file)` only (never the template), 2-space pretty JSON + trailing newline; create parent dir if needed; return the path. Never write if `app.config_file is None` (raise `ValueError`).
- `expand_preview(value: str) -> str` — `os.path.expandvars` (expands `%USERPROFILE%` etc.) for display only.

## `config/validation.py`
- `validate(descriptors: list[FieldDescriptor], values: dict) -> dict[str, str]` — return `{dot_key: error}` (empty = valid). Rules: required + non-empty + not a `YOUR_...` placeholder; `installed.client_id` matches `^\d+-.+\.apps\.googleusercontent\.com$`; `notesDirectories` non-empty list of non-empty strings. Use `descriptors.flatten` for lookups.

## TUI (Textual) — `tui/*`
Engine API the screens call: `manifest.load_registry`, `prerequisites.check_all`, `ProcessManager`, `prepare.needs_prepare/run_prepare`, `config.descriptors.descriptors_for`, `config.io.load_values/save_values`, `config.validation.validate`.
- `widgets.py`:
  - `class StatusBadge(Static)` — `set_status(status: str)` -> renders ● running (green) / ○ stopped (dim).
  - `class SecretInput(Widget)` — wraps an `Input(password=True)` + a reveal toggle (`Button`/key) flipping `password`. `value` property.
  - `class StringListEditor(Widget)` — a list with Add/Remove/Up/Down for `list[str]`; `values: list[str]` property; seeded via constructor.
- `arg_picker_screen.py`:
  - `class ArgPickerScreen(ModalScreen[str | None])` — constructed with `choices: list[ArgChoice]` and `label: str`. Renders an `OptionList` of `choice.label` entries (with `choice.description` as a subtitle where available) plus **Launch** and **Cancel** buttons. Dismisses with `choice.value` on Launch or `None` on Cancel/Escape. Never imports engine modules; the caller resolves the value.
- `app_list.py`:
  - `class AppListScreen(Screen)` — constructor `(registry: Registry, pm: ProcessManager, repo_root: Path)`. A `DataTable` (or `ListView`) row per app: icon+name, stack, prereq summary, status. Bindings/buttons: **Launch** (run prepare if needed, then `pm.launch`), **Stop** (enabled only if `app.stoppable`), **Config** (`push_screen(ConfigScreen(...))`, only if `app.config_file`), **Refresh** status (also auto-polled every ~1.5 s via `set_interval`, so an app you close yourself flips to *stopped* without pressing Refresh). Show prereq failures inline (don't launch if a hard prereq fails). When `app.launch.arg_picker` is set, Launch first calls `arg_picker.discover_choices(repo_root, app)`, pushes `ArgPickerScreen`, and — if a non-`None` value is returned — calls `pm.launch(repo_root, app, extra_args=[value])`.
- `config_screen.py`:
  - `class ConfigScreen(Screen)` — constructor `(app: App, repo_root: Path)`. On mount: `load_values`, `descriptors_for`, build a form (text/secret/string-list/file-path widgets). **Save** validates then `save_values`; show errors inline. For `credentials.json` offer an "Import…" path `Input` that loads a Google JSON and fills fields. `token.json` is not edited here.
- `app.py`:
  - `class MicroAppsLauncher(App)` — `CSS_PATH = "app.tcss"`. On mount: `repo_root = paths.find_repo_root()`, `registry = manifest.load_registry(repo_root)`, `pm = ProcessManager()`, `push_screen(AppListScreen(registry, pm, repo_root))`. A header showing a `pyfiglet`/`rich` "MicroApps" banner. Bindings: `q` quit, `r` refresh.
  - `def run_app() -> None` — construct and `.run()`.

## `launcher.py` (entry)
- Add `Path(__file__).parent` to `sys.path` so `microapps_launcher` imports.
- `--check` (or `check`): **headless**, do NOT import textual. `root = find_repo_root()`; `load_registry`; for each app print prereq results (`check_all`) and prepare status (`needs_prepare`). Exit 0 if all manifest valid (non-zero on `ManifestError`). This is the verification entry point.
- `--list`: print app ids/names.
- no args: lazy-import `microapps_launcher.tui.app` and `run_app()`.
- Use `argparse`.

## Tests (`tests/`)
- pytest, run from `AppLauncher/` (`python -m pytest`). Import as `from microapps_launcher.x import y`.
- Engine tests are pure (no textual). Use `tmp_path` to fake repo roots/sentinels; monkeypatch `shutil.which`/`subprocess` for prerequisites/process tests. `test_integration.py` loads the **real** `../apps.json` (resolve via `find_repo_root`), validates it, builds descriptors for both config templates, and runs `check_all` for each app (asserting it returns results without raising).
