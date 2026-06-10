# MicroApps Launcher — Architecture & Module Contracts

This document is the **integration contract**. Each module is implemented by a
separate agent; everyone codes against the signatures below so the pieces fit.

## Package layout
```
app-launcher/
  launcher.py              # entry point (lazy-imports tui; --check is headless)
  launcher.bat             # `python launcher.py %*`
  requirements.txt         # textual, rich, pyfiglet
  microapps_launcher/
    __init__.py
    models.py              # DONE (contract): Registry, App, Launch, Prepare, Prerequisite
    paths.py               # repo-root + path/command resolution
    manifest.py            # load + validate apps.json -> Registry
    prerequisites.py       # detect runtimes; PrereqResult
    process_manager.py     # spawn/track/stop per launchMode
    prepare.py             # build-once sentinel + run prepare
    config/
      __init__.py
      descriptors.py       # FieldDescriptor + infer from *.example.json
      io.py                # load/save config values (git-ignored real file)
      validation.py        # per-field validation
    tui/
      __init__.py
      app.py               # MicroAppsLauncher(App)
      app_list.py          # AppListScreen
      config_screen.py     # ConfigScreen
      widgets.py           # StatusBadge, SecretInput, StringListEditor
      app.tcss             # styling
  tests/                   # pytest; one module per engine file + integration
```

## Hard rules
- **Python 3.11+**, PEP 8, **type annotations on every signature**, `from __future__ import annotations` at the top of every module.
- **Immutability:** never mutate inputs; return new objects. Models are frozen dataclasses.
- **Engine modules** (`paths`, `manifest`, `prerequisites`, `process_manager`, `prepare`, `config/*`) **must NOT import `textual`** — stdlib only (`manifest.py` may *optionally* use `jsonschema` with a stdlib fallback). This keeps `--check` runnable without the TUI deps.
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

## `process_manager.py`
- `class ProcessManager:` holds `self._procs: dict[str, subprocess.Popen]`.
  - `launch(self, root: Path, app: App) -> None` — build argv via `paths.resolve_command`; spawn with `cwd=resolve_cwd(...)`. Windows creation flags by `app.launch_mode`:
    - `console` -> `CREATE_NEW_CONSOLE`; store handle under `app.id`.
    - `gui` -> flags `0` (no redirection); store handle.
    - `fire-and-forget` -> `DETACHED_PROCESS | CREATE_NO_WINDOW`; do **not** store.
    - Use `getattr(subprocess, "CREATE_NEW_CONSOLE", 0)` etc. so it imports on non-Windows. Never redirect stdio.
  - `status(self, app_id: str) -> str` — `"running"` if a stored handle has `poll() is None`, else `"stopped"`.
  - `stop(self, app_id: str) -> None` — if tracked: `terminate()`, wait up to ~3s, then `kill()`; drop the handle. No-op if untracked.
  - `is_running(self, app_id: str) -> bool`.
- Pure stdlib (`subprocess`, `sys`). Must import cleanly on any OS (guard flags).

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
  - `class StatusBadge(Static)` — `update_status(status: str)` -> renders ● running (green) / ○ stopped (dim).
  - `class SecretInput(Widget)` — wraps an `Input(password=True)` + a reveal toggle (`Button`/key) flipping `password`. `value` property.
  - `class StringListEditor(Widget)` — a list with Add/Remove/Up/Down for `list[str]`; `values: list[str]` property; seeded via constructor.
- `app_list.py`:
  - `class AppListScreen(Screen)` — constructor `(registry: Registry, pm: ProcessManager, repo_root: Path)`. A `DataTable` (or `ListView`) row per app: icon+name, stack, prereq summary, status. Bindings/buttons: **Launch** (run prepare if needed, then `pm.launch`), **Stop** (enabled only if `app.stoppable`), **Config** (`push_screen(ConfigScreen(...))`, only if `app.config_file`), **Refresh** status. Show prereq failures inline (don't launch if a hard prereq fails).
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
- pytest, run from `app-launcher/` (`python -m pytest`). Import as `from microapps_launcher.x import y`.
- Engine tests are pure (no textual). Use `tmp_path` to fake repo roots/sentinels; monkeypatch `shutil.which`/`subprocess` for prerequisites/process tests. `test_integration.py` loads the **real** `../apps.json` (resolve via `find_repo_root`), validates it, builds descriptors for both config templates, and runs `check_all` for each app (asserting it returns results without raising).
