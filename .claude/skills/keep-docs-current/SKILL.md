---
name: keep-docs-current
description: Project rule for the MicroApps repo — whenever you CHANGE an existing app's user-visible surface (behavior, UI, hotkeys, CLI flags/commands, prerequisites, dependencies, or data/storage locations), you MUST update its docs AND the repo-root README + apps.json blurb in the SAME change. Use when modifying, refactoring, reworking, or finishing work on an existing app here.
---

# Keep docs current when you change an app

This monorepo's docs are layered: each app has its own docs, and the **repo-root
`README.md`** + the launcher manifest **`apps.json`** are the *front door* that
describe every app in one place. Those front-door docs drift silently — a change
to an app's behavior is **not "done" until every doc that describes it matches
reality, in the SAME change.**

This is the companion to **add-app-to-launcher**: that rule covers *adding a new
app*; this rule covers *changing an existing one*.

## The rule

When you change an existing app's **user-visible surface**, update every doc that
describes it, in the same commit. "User-visible surface" = anything a user or
operator would notice:

- behavior or features (what it does)
- UI / layout / tabs / panels
- hotkeys / keybindings
- CLI flags, subcommands, or arguments
- prerequisites or minimum versions
- dependencies (added/removed)
- data, config, or storage locations

A pure internal refactor with **no** user-visible change does not require
front-door edits — but still fix the app's `ARCHITECTURE.md` if it now describes
the internals wrongly.

## What to update (in the same change)

1. **The app's own docs** — `<App>/README.md`, plus `<App>/ARCHITECTURE.md` and
   `<App>/PLAN.md` when they exist (e.g. `CCDashboard/`, `ClaudeBench/`). Update
   the feature list, hotkey tables, flags, prerequisites, and any data-flow or
   design sections affected.
2. **The repo-root `README.md`** — the app's **row in the app table**
   (`| App | Stack | What it does |`) AND its **line in the file-tree block**, if
   the headline of what the app does (or its marquee features) changed.
3. **`apps.json`** — the app's **`description`** (the launcher blurb shown in
   AppLauncher), if that one-liner is now inaccurate. Keep the JSON valid and the
   existing field order/formatting.

## Verify (before committing)

- `grep -nE '<AppName>|<app-id>' README.md apps.json` — confirm the table row,
  the file-tree line, and the launcher blurb all match the new reality.
- If you touched `apps.json`:
  `python -c "import json; json.load(open('apps.json', encoding='utf-8'))"` (valid
  JSON), and ideally `python AppLauncher/launcher.py --list` (the blurb renders).
- Re-read the app's `README.md` intro + feature list against the code you changed
  — does anything still describe the old behavior?

## Notes

- Folder names are PascalCase (`CCDashboard`); the `apps.json` `id` is kebab-case
  (`cc-dashboard`) — search for **both** when verifying.
- If a change adds/removes a whole feature area (a new tab, a new command), expect
  to touch all three layers; a small flag tweak may only need the app README.
- Don't rely on memory of what the docs say — open them and check. The root
  README and `apps.json` are easy to forget precisely because they live far from
  the code you edited.
