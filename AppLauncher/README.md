# MicroApps Launcher

A small **Textual TUI** that configures and launches the apps in this repo from a
single manifest (`apps.json` at the repo root) — regardless of stack. It reads
the registry, checks each app's prerequisites, runs any one-time build/install
step, then launches (and, where possible, stops) the app.

## Install

```powershell
cd AppLauncher
pip install -r requirements.txt   # textual, rich, pyfiglet (+ optional jsonschema)
```

The engine and the headless `--check`/`--list` commands are **stdlib-only** — you
only need the dependencies above to run the interactive TUI.

## Run

```powershell
python launcher.py            # interactive TUI: list apps, Launch / Stop / Config
python launcher.py --check    # headless: validate apps.json + run prerequisite checks
python launcher.py --list     # list the registered apps
```

On Windows you can also double-click / run `launcher.bat` (it forwards args).

## What it does

- **Prerequisites** — verifies Python / .NET SDK / Windows Terminal etc. per app, with fix hints.
- **Prepare (build-once)** — runs `pip install` / `dotnet build` only when needed (skipped once the sentinel exists, e.g. the built `.exe`).
- **Launch modes** — `console` apps open their own terminal window; `gui` apps run as a window; `fire-and-forget` apps (ClaudePanes) are detached.
- **Live status** — each app shows a running/stopped badge that **auto-refreshes** (polled every ~1.5 s), so an app you close yourself flips to *stopped* on its own; `Stop` terminates a tracked app when it's marked `stoppable`.
- **Config editor** — edits each app's settings in the git-ignored `config/` folder (masked secrets; never writes templates). `Config` button per app.

## Adding a new app

Add one entry to `apps.json` (validated by `apps.schema.json`) — no launcher code
changes. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the manifest schema, the
module contracts, and the path-resolution rules.

## Layout

```
launcher.py              entry point (--check / --list / TUI)
microapps_launcher/
  models.py              manifest data models
  paths.py               repo-root + path/command resolution
  manifest.py            load + validate apps.json
  prerequisites.py       runtime detection
  process_manager.py     spawn / track / stop
  prepare.py             build-once sentinel + run
  config/                descriptors, load/save, validation
  tui/                   Textual app, screens, widgets, styling
tests/                   pytest (engine is testable headless)
```
