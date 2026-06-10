# MicroApps Launcher — Plan & Progress

A single cross-stack "hub" app to **edit each micro-app's config via a UI** and
**launch/stop any app regardless of stack** from one place.

> This plan was produced from a 10-agent parallel research pass over the repo
> (per-app launch contracts, four UI-stack evaluations, and three cross-cutting
> design tracks: manifest, config-editor, process management).

---

## 1. Goal

One window/page where you can:
- See all three apps (and any future app) with a status badge.
- Edit each app's sensitive/machine-specific config through a form (writing only
  to the git-ignored `config/` folder).
- **Prepare** (build/install) and **Launch** any app, and **Stop** the ones that
  are stoppable — without caring whether it's Python, .NET, or anything else.

Adding a future app should mean **adding one manifest entry, not changing
launcher code**.

---

## 2. The launch targets (researched contracts)

| App | Stack | Launch | Mode | Config | Stop |
|-----|-------|--------|------|--------|------|
| **MeetingTracker** | Python `rich` TUI | `python meeting_tracker.py` (use `sys.executable`) in `MeetingTracker/` | **console** — needs its own interactive window (`CREATE_NEW_CONSOLE`); `msvcrt` + `rich` alt-screen break if stdio is redirected | `config/credentials.json` (+ auto `config/token.json`) | `terminate()`; window closes itself |
| **meeting-notes-overlay** | .NET 10 WinUI 3 (`WinExe`) | build once `dotnet build -c Release`, then run `bin/Release/net10.0-windows10.0.22621.0/MeetingNotesOverlay.exe` | **gui** — no console, no single-instance guard | `config/meeting-notes-overlay.json` | `CloseMainWindow()` → wait 3s → `Kill()` |
| **ClaudePanes** | Python 3.11+ CLI | `python claude_panes.py start <layout>` in `ClaudePanes/` | **fire-and-forget** — spawns a terminal multiplexer then exits | none (layouts live in `~/.config/claude-panes/`) | n/a — nothing persistent to stop |

Key facts surfaced by the research:
- **MeetingTracker** first run blocks 10–60s on an **OAuth browser popup** and writes `token.json`. The launcher should show a "starting (OAuth pending)…" state, not assume a hang. If `credentials.json` is missing it `sys.exit(1)`.
- **meeting-notes-overlay** config walk-up (`AppContext.BaseDirectory` → up to repo root) **correctly** finds `config/meeting-notes-overlay.json` from the `bin/...` output dir. First build is slow (~30–60s); use a **build-once sentinel** (the `.exe`) so later launches skip it.
- **ClaudePanes** has no secrets and nothing to stop. In the UI it should be a **layout picker** (enumerate via `claude-panes list --json`, "Launch" a selected layout), not a start/stop card.

---

## 3. Architecture — manifest-driven

The launcher reads a stack-agnostic **`apps.json`** registry at the repo root. The
launcher engine only knows how to: check prerequisites → run an optional prepare
step (build-once) → spawn per `launchMode` → track/stop. It infers nothing from
the `stack` field (that's cosmetic); the actual command lives in `launch.cmd`.

### Manifest schema (per app)

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Stable unique key (`meeting-tracker`) |
| `name` / `description` | string | Display text |
| `stack` | enum | `python` \| `dotnet` \| `node` \| `binary` … (display/grouping only) |
| `icon` | string? | PNG/ICO path or emoji |
| `cwd` | string | Working dir for prepare+launch, relative to repo root |
| `prepare` | object? | One-time setup: `{ cmd: string[], sentinel: string? }`. If `sentinel` file exists → skip. `null` sentinel ⇒ run every cold start (idempotent installs) |
| `launch` | object | `{ cmd: string[] }` (argv; no shell expansion) |
| `launchMode` | enum | `gui` \| `console` \| `fire-and-forget` → drives spawn flags |
| `stoppable` | bool | Whether Stop is meaningful |
| `configFile` | string? | Repo-relative live (git-ignored) config |
| `configTemplate` | string? | Committed `*.example.json` to seed from |
| `configSchema` | string? | Optional JSON Schema for form rendering |
| `prerequisites` | check[] | e.g. `{type:"python",minVersion:"3.11"}`, `{type:"dotnet-sdk",minVersion:"10.0"}`, `{type:"binary",name:"wt.exe"}` |
| `docs` | string? | README/url |

### Drafted `apps.json` (to be created in Phase 1)

```json
{
  "$schema": "./apps.schema.json",
  "version": "1",
  "apps": [
    {
      "id": "meeting-tracker",
      "name": "Meeting Tracker",
      "description": "Rich TUI — live calendar, countdown timers, Gmail inbox, one-key join.",
      "stack": "python",
      "cwd": "MeetingTracker",
      "prepare": { "cmd": ["pip", "install", "-r", "requirements.txt"], "sentinel": ".deps_installed" },
      "launch": { "cmd": ["python", "meeting_tracker.py"] },
      "launchMode": "console",
      "stoppable": true,
      "configFile": "config/credentials.json",
      "configTemplate": "config/credentials.example.json",
      "configSchema": null,
      "prerequisites": [{ "type": "python", "minVersion": "3.7" }],
      "docs": "MeetingTracker/README.md"
    },
    {
      "id": "meeting-notes-overlay",
      "name": "Meeting Notes Overlay",
      "description": "Always-on-top WinUI 3 overlay invisible to screen capture.",
      "stack": "dotnet",
      "cwd": "meeting-notes-overlay",
      "prepare": { "cmd": ["dotnet", "build", "-c", "Release"], "sentinel": "bin/Release/net10.0-windows10.0.22621.0/MeetingNotesOverlay.exe" },
      "launch": { "cmd": ["bin/Release/net10.0-windows10.0.22621.0/MeetingNotesOverlay.exe"] },
      "launchMode": "gui",
      "stoppable": true,
      "configFile": "config/meeting-notes-overlay.json",
      "configTemplate": "config/meeting-notes-overlay.example.json",
      "configSchema": null,
      "prerequisites": [{ "type": "dotnet-sdk", "minVersion": "10.0" }],
      "docs": "meeting-notes-overlay/README.md"
    },
    {
      "id": "claude-panes",
      "name": "Claude Panes",
      "description": "Fire-and-forget TOML-driven Claude Code pane-layout launcher.",
      "stack": "python",
      "cwd": "ClaudePanes",
      "prepare": null,
      "launch": { "cmd": ["python", "claude_panes.py", "start"] },
      "launchMode": "fire-and-forget",
      "stoppable": false,
      "configFile": null,
      "configTemplate": null,
      "configSchema": null,
      "prerequisites": [
        { "type": "python", "minVersion": "3.11" },
        { "type": "binary", "name": "wt.exe" }
      ],
      "docs": "ClaudePanes/README.md"
    }
  ]
}
```
> ClaudePanes' `launch.cmd` intentionally omits the layout — the UI appends the
> chosen layout name/path as a final argv element.

---

## 4. Config-editor design

- **Field descriptors** drive a generic form: `{ key (dot-path), label, type, secret?, required?, help }`. Types: `text`, `secret` (masked + reveal toggle), `string-list` (add/remove/reorder — for `notesDirectories`), `file-path` (import a `credentials.json`), `readonly` (token status). Descriptors can be inferred from the `*.example.json` shape or supplied via an optional JSON Schema.
- **Load:** if `config/<app>.json` is missing, seed the form from `config/<app>.example.json`; strip placeholder sentinels (`YOUR_…`) to empty. Never write the `.example` file.
- **Save:** validate → re-nest dot-paths (e.g. back under `installed`) → preserve untouched keys → pretty-print → write **only** the git-ignored real file.
- **Secrets:** mask by default, reveal toggle, never logged; header note "stored only in the git-ignored `config/` folder, never leaves this machine."
- **Env vars:** store `%USERPROFILE%\TODOs` literally; show an expanded preview beside it.
- **MeetingTracker specials:** "Import credentials.json…" file-picker that validates the `{ installed: { client_id, client_secret, … } }` shape and copies it to `config/credentials.json`; `token.json` shown **read-only** (Present/expires-at / Expired / Missing) with a "Delete token (force re-auth)" button.
- **Validation:** `client_id` matches `^\d+-.+\.apps\.googleusercontent\.com$`, `client_secret`/`project_id` required & not placeholder; `notesDirectories` non-empty list of non-empty strings (warn, don't block, if a path doesn't exist).

---

## 5. Process management design (Windows-first)

- **Spawn recipes:**
  - `console` (MeetingTracker): `Popen([sys.executable, "meeting_tracker.py"], cwd=…, creationflags=CREATE_NEW_CONSOLE)` — **no** stdio redirection (it breaks `msvcrt`/`rich`). .NET equivalent needs P/Invoke or `UseShellExecute=true`.
  - `gui` (overlay): `Popen([exe], cwd=…)`, no special flags, no redirection.
  - `fire-and-forget` (ClaudePanes): `Popen([...], creationflags=DETACHED_PROCESS|CREATE_NO_WINDOW)`, discard the handle.
- **Tracking:** hold `{id: (pid, handle)}`; liveness via `poll()`/`HasExited`. Don't track fire-and-forget. Optional PID-sidecar (with process **start-time** to defeat PID recycling) to reconnect after a launcher restart — worth it for the two long-lived apps only.
- **Stopping:** overlay → `CloseMainWindow()` then `Kill()` after 3s; MeetingTracker → `terminate()`/`Kill()` (its console window closes itself); ClaudePanes → disabled.
- **Prerequisites:** `python --version` (prefer `sys.executable`), `dotnet --list-sdks` (need a `10.*` line), `shutil.which("wt")` (+ wezterm/tmux/zellij fallback). Missing → clear message + install URL, disable that app's Launch until it passes.
- **Prepare:** stream `dotnet build` / `pip install` output live (line-buffered, not `communicate()`); build-once via sentinel (the `.exe`; for pip, a `.deps_installed` invalidated when `requirements.txt` is newer); non-zero exit → show last lines + "Retry", never auto-retry.
- **Windows gotchas to design around:**
  1. **"python" ≠ launcher's python** (venv / Microsoft Store stub). Prefer `sys.executable` for the Python apps.
  2. **`CREATE_NEW_CONSOLE` + `CTRL_C_EVENT` doesn't cross process groups** — use `terminate()`, or have the app handle `CTRL_BREAK_EVENT` (sendable to a specific PID).
  3. **First-run OAuth latency** — have MeetingTracker write a `…_ready` sentinel once `rich.Live` starts; launcher shows "starting (OAuth pending)…" until then.

---

## 6. UI stack — TUI (chosen direction) ⛳

Per the steer, the launcher will be a **terminal UI in the same spirit as
MeetingTracker**, reusing the `rich` ecosystem. Two flavors:

| Flavor | Libraries | Forms / input | New deps | Verdict |
|--------|-----------|---------------|----------|---------|
| **Textual** ⭐ | `textual` (built on `rich`, same authors) + `pyfiglet` banner | Real interactive widgets: `Input(password=True)` for secrets, `Button`, `ListView`/`OptionList` for the `notesDirectories` editor, `DataTable` for the app list, `Screen`s, tab/focus nav, mouse + keyboard, CSS-like styling | `textual` (`rich` already present) | **Recommended** — a true TUI *app framework*; makes config forms pleasant while staying 100% terminal + rich-family |
| **Pure `rich` + `msvcrt`** | exactly MeetingTracker's stack — `rich` (Live/Table/Panel/Layout) + `msvcrt` key polling + `pyfiglet` | Hand-rolled: build text entry, secret masking, list editing yourself (like MeetingTracker's nav loop) | **zero** | Literal "same libraries, no new deps" — at the cost of hand-writing input widgets |

Why a TUI fits well here:
- Pure Python; **reuses the repo's existing `rich` dependency**; no compile step; `python launcher.py` and you're in.
- Consistent aesthetic with MeetingTracker and the terminal-oriented ClaudePanes.
- Launching is clean: every target opens its **own** window (MeetingTracker's new console, the overlay GUI, ClaudePanes' terminals), so the launcher TUI just spawns and stays put — no output embedding needed.

TUI caveats (vs a GUI) and how we handle them:
- **No native file dialog** for "Import credentials.json" → a path `Input` (paste the downloaded path) or a Textual `DirectoryTree` mini-browser.
- **Secret reveal-toggle** → `Input(password=True)` masks; a key/button flips `password=False` to reveal.
- **Keyboard-first** (Textual also supports mouse) — appropriate for a dev tool.

Everything else in this plan (manifest, process management, config-editor *logic*,
prerequisite detection) is **presentation-agnostic and unchanged** — only the
rendering layer differs.

> GUI/web alternatives (PySide6, Tkinter, FastAPI web, .NET WPF) were evaluated and
> remain viable fallbacks if the TUI's config-editing ergonomics ever feel too
> constrained; the manifest + engine port to any of them unchanged.

**Decided: Textual** (2026-06-01) — `rich` family + `textual` for real interactive form widgets.

---

## 7. Checklist

### Phase 0 — Foundations ✅ (done in the security/config pass)
- [x] Central git-ignored `config/` folder + `*.example.json` templates + README
- [x] `config/.gitignore` (ignore-all-but-templates) verified working
- [x] MeetingTracker reads `config/credentials.json` + `config/token.json` (`CONFIG_DIR`)
- [x] meeting-notes-overlay reads `config/meeting-notes-overlay.json` (walk-up loader, env-var expansion, safe fallback)
- [x] Secrets relocated out of `MeetingTracker/`; never committed (verified); de-personalized source/docs; purged 85MB `bin/obj`

### Phase 1 — Manifest + skeleton ✅
- [x] **Confirm TUI flavor** — **Textual** chosen (rich-family; adds `textual`)
- [x] Add `app-launcher/requirements.txt` (`textual`, `rich`, `pyfiglet`; pinned + `pip-audit`-clean)
- [x] `apps.json` (+ `apps.schema.json`) at repo root
- [x] Launcher reads manifest, renders the app list with status badges
- [x] Prerequisite detection (python / dotnet-sdk net10 / wt.exe) + fix hints

### Phase 2 — Launch / prepare / stop ✅
- [x] Spawn per `launchMode` with correct Windows flags
- [x] Build-once prepare with sentinel + streamed output
- [x] Running-state tracking; Stop (overlay/MeetingTracker terminate→kill; ClaudePanes disabled)

### Phase 3 — Config editor (mostly done)
- [x] Generic descriptor-driven form (text / secret / string-list) — `file-path`/`readonly` types render as text for now
- [x] Load-from-example fallback; save only to git-ignored real file; structure-preserving
- [ ] MeetingTracker "Import credentials.json"; `token.json` read-only status — *deferred*
- [x] Validation rules — `expand_preview` helper exists; live env-var preview not yet wired into the form

### Phase 4 — Polish (partial)
- [x] Status badges + error surfacing (prepare output tail shown on failure) — live-log panel not built
- [ ] First-run OAuth "starting…" handling (ready sentinel) — *deferred*
- [ ] ClaudePanes layout picker — ⚠️ **needed for ClaudePanes to launch**: its `start` requires a `<layout>` and the manifest currently passes none
- [x] Entry point (`launcher.bat`) + `app-launcher/README.md` + root README link — PyInstaller packaging/icon not done

### Phase 5 — Optional
- [ ] PID-sidecar reconnect across launcher restarts
- [ ] "Add a new app" doc (manifest-only workflow)
- [ ] Per-app Python venv management (vs global / `sys.executable`)

---

## 8. Open questions
1. ~~TUI flavor~~ — **Resolved: Textual** (2026-06-01).
2. **Python isolation** — global interpreter / `sys.executable`, or a managed venv per Python app?
3. **Tray icon + autostart at login** — wanted, or launch-on-demand only?
4. **Scope** — stays Windows-only (all 3 apps are), or keep cross-platform in mind?

---

## 9. Progress log
- **2026-06-01** — Plan created from a 10-agent parallel research pass. Phase 0 (central config foundation) already complete from the pre-public security cleanup.
- **2026-06-01** — Direction set to a **TUI** in the `rich` family (per user), reusing MeetingTracker's ecosystem. **Textual** recommended over pure `rich`+`msvcrt`. Plan §6 updated; engine/manifest/config-logic unchanged.
- **2026-06-01** — Textual confirmed. **Phase 1 started**: ran a 10-agent verification fan-out to ground-truth the manifest (per-app entries, JSON Schema, prerequisite floors, path-existence audit, path-resolution contract). Corrections found: MeetingTracker Python floor is **3.8** (not 3.11 — code converts `Z`→`+00:00` before `fromisoformat`; `rich` sets the 3.8 floor); the overlay `dotnet build -c Release` outputs to `bin/Release/<TFM>/` with **no arch subfolder**; ClaudePanes' terminal prereq is **any-of** `wt`/`wezterm`/`tmux`/`zellij`.
- **2026-06-01** — ⏸️ **PAUSED (resume here):** all manifest data is verified but `apps.json` + `apps.schema.json` are **not yet written to disk** — that's the next action. Verified per-app fields, the authored schema, and the path-resolution contract are in the session handoff (`summary.md`). After writing the two files, tick the Phase 1 box below; then continue with `app-launcher/requirements.txt` + the Textual skeleton.

- **2026-06-09** — ✅ **Launcher built & verified.** Wrote `apps.json` + `apps.schema.json`, the engine (`paths`/`manifest`/`prerequisites`/`process_manager`/`prepare`), the config layer, and the full Textual TUI (`launcher.py` + screens/widgets). Verified on-machine: `--check` (manifest valid, live prereq detection), `--list`, and a headless Textual `run_test()` pilot all pass. Fixes along the way: Textual `_registry` attr collision (namespaced instance attrs to `_ma_*`), Windows cp1252 unicode crash (utf-8 `reconfigure`), and the overlay prepare ambiguity (`dotnet build` → `dotnet build MeetingNotesOverlay.csproj`, since that folder has both a `.sln` and a `.csproj`). Deps `pip-audit`-clean + pinned. Phases 1–2 ✅, Phase 3 mostly ✅. Remaining: ClaudePanes layout picker (currently blocks ClaudePanes launch), credentials-import, OAuth ready-sentinel, packaging.

<!-- Append dated entries here as phases complete. Tick boxes in §7. -->
