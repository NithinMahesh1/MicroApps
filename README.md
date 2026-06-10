# MicroApps

A small mono-repo of personal Windows micro-apps, plus a unified **launcher** that
configures and runs any of them from one place — regardless of stack.

## Apps

| App | Stack | What it does |
|-----|-------|--------------|
| [**MeetingTracker**](MeetingTracker/) | Python (`rich` TUI) | Live terminal dashboard of today's Google Calendar meetings — countdowns, alerts, one‑key join, and unread Gmail. |
| [**meeting-notes-overlay**](meeting-notes-overlay/) | .NET 10 / WinUI 3 | Always‑on‑top notes overlay that is **invisible to screen sharing** (Teams/Slack/Zoom/Meet) via `WDA_EXCLUDEFROMCAPTURE`. |
| [**ClaudePanes**](ClaudePanes/) | Python CLI | Opens multi‑pane Claude Code terminal layouts from a TOML file (Windows Terminal / WezTerm / tmux / Zellij). |

## Launcher

[`app-launcher/`](app-launcher/) is a **Textual TUI** that lists every app, checks
its prerequisites, runs any one‑time build/install step, then launches (and stops)
it. It's driven by a manifest — [`apps.json`](apps.json), validated by
[`apps.schema.json`](apps.schema.json) — so adding a new app is **one manifest entry,
no launcher code**.

```powershell
cd app-launcher
pip install -r requirements.txt
python launcher.py            # interactive TUI: Launch / Stop / Config per app
python launcher.py --check    # headless: validate manifest + run prerequisite checks
python launcher.py --list     # list registered apps
```

The engine and `--check`/`--list` are **stdlib‑only**; only the interactive TUI needs
the dependencies above (all `pip-audit`‑clean and version‑pinned).

## Configuration & secrets

All sensitive or machine‑specific settings live in the **git‑ignored**
[`config/`](config/) folder. Real files (`credentials.json`, `token.json`,
`meeting-notes-overlay.json`) never leave your machine; only `*.example.json`
templates and a setup guide are committed. Copy a template, fill in your values (or
use the launcher's **Config** button), and you're set — see
[`config/README.md`](config/README.md).

## Requirements

- Windows 10 (build 19041+) / Windows 11
- Python 3.11+ — MeetingTracker, ClaudePanes, the launcher
- .NET 10 SDK — meeting-notes-overlay
- A terminal multiplexer for ClaudePanes (e.g. Windows Terminal)

## Layout

```
apps.json / apps.schema.json   launcher manifest + JSON Schema
app-launcher/                  Textual launcher (engine + TUI + tests; see its ARCHITECTURE.md)
config/                        git-ignored secrets/settings + committed templates
MeetingTracker/                Python calendar/Gmail TUI
meeting-notes-overlay/         .NET 10 WinUI 3 capture-proof overlay
ClaudePanes/                   Python terminal-layout launcher
```
