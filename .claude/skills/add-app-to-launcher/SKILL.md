---
name: add-app-to-launcher
description: Project rule for the MicroApps repo — whenever you add a NEW app/folder to this monorepo, you MUST also register it in the AppLauncher manifest (apps.json). Use when creating, scaffolding, or finishing a new app here.
---

# Always register new apps in AppLauncher

This monorepo ships a launcher (`AppLauncher/`) that lists and runs every app from
a single manifest, **`apps.json`** (validated by `apps.schema.json`). The launcher
is the front door to every app, so **a new app is not "done" until it appears in
the launcher.**

## The rule

When you add a new application to this repo (a new top-level folder with its own
entry point), in the SAME change you must add a corresponding entry to the `apps`
array in `apps.json`.

## How to add the entry

1. Open `apps.json` (repo root) and `apps.schema.json` for the exact field
   contract. Copy the shape/field order of an existing entry (e.g. `meeting-tracker`
   or `cc-dashboard`).
2. Add one object to the `apps` array with these fields:
   - `id` — kebab-case, unique (schema-enforced), e.g. `"my-new-app"`.
   - `name`, `description`, `stack` (`python` | `dotnet` | `node` | `binary`), `icon` (emoji).
   - `cwd` — the app's folder, relative to the repo root (forward slashes).
   - `prepare` — a one-time build/install step `{ "cmd": [...], "sentinel": <path|null> }`, or `null`.
   - `launch` — `{ "cmd": [...] }`; the literal `"python"` resolves to the launcher's interpreter.
   - `launchMode` — `"console"` | `"gui"` | `"fire-and-forget"`.
   - `stoppable` — boolean (MUST be `false` when `launchMode` is `fire-and-forget`).
   - `configFile` / `configTemplate` / `configSchema` — paths under the git-ignored
     `config/` folder, or `null`.
   - `prerequisites` — array of checks (`python` / `dotnet-sdk` / `node` / `binary` /
     `binary-any` / `os`), e.g. `[ { "type": "python", "minVersion": "3.11" } ]`.
   - `docs` — path to the app's README, e.g. `"MyNewApp/README.md"`.
3. Keep JSON valid (commas/brackets); preserve the existing formatting.

## Verify

- `python AppLauncher/launcher.py --list` — the new app appears in the list.
- `python AppLauncher/launcher.py --check` — its `cwd` resolves and prerequisites pass.

## Notes

- Folder naming convention in this repo is **PascalCase** (e.g. `MeetingTracker`,
  `ClaudeBench`, `CCDashboard`); the app `id` stays kebab-case.
- If the app needs secrets/config, add the git-ignored real file + a committed
  `*.example.json` template under `config/` and point `configFile`/`configTemplate`
  at them.
