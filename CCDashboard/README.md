# CCDashboard

A read-only **Jarvis HUD dashboard** that visualises your entire global Claude Code
config (`~/.claude/`) as a self-contained HTML file and opens it in your browser.
No server, no network — pure Python stdlib generates `dist/dashboard.html` with all
CSS, JS, and data inlined, then hands it off to the OS.

> **ClaudeBench reuse:** CCDashboard imports the scanner from the sibling
> `ClaudeBench/` app to enumerate config items, and reads the newest
> `ClaudeBench/snapshots/*.json` for per-item token costs when available.
> ClaudeBench itself is unchanged and still runs fully standalone (`list`,
> `snapshot`, `diff`, `bench`).

---

## Prerequisites

- **Python 3.11+** — stdlib only; no `pip install` required for CCDashboard.
- **A web browser** — the generated file is opened automatically with
  `webbrowser.open`.
- **Optional:** run a ClaudeBench `snapshot` first to populate token cost columns.
  Without a snapshot the dashboard still shows all items; token fields are left blank.

```powershell
# One-time (optional) — capture token costs so the dashboard can display them
cd ClaudeBench
pip install -r requirements.txt
python claude_bench.py snapshot --label before-session
```

---

## Run

```powershell
python CCDashboard/cc_dashboard.py
```

The command scans `~/.claude/`, builds `CCDashboard/dist/dashboard.html`, and opens
it in your default browser.

### Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--config-dir DIR` | `~/.claude` | Path to the Claude Code config directory to scan |
| `--out PATH` | `CCDashboard/dist/dashboard.html` | Where to write the generated file |
| `--no-open` | *(opens by default)* | Build the file without launching the browser |

```powershell
# Build only, custom config dir
python CCDashboard/cc_dashboard.py --config-dir D:\alt-claude --no-open

# Custom output path
python CCDashboard/cc_dashboard.py --out C:\tmp\hud.html
```

---

## What you see

The dashboard uses a **Jarvis / Iron-Man HUD aesthetic** — dark background,
blue-cyan arc-reactor canvas centerpiece, glassmorphism panels, and animated
scanlines.

**Six per-kind summary panels** (skill, agent, memory, rule, setting, mcp) each
show an animated count-up to the total for that kind.

**Card grid** — every config item is a card showing kind badge, name, description,
file size, and last-modified date. Use the **search box** to filter by text, or
click a **kind chip** to filter by category.

**Detail drawer** — clicking any card slides in a drawer with the full item details:
kind, path, file size, token costs (always-loaded and invocation), description, and
a content preview. Token cost columns appear only when a ClaudeBench `count_tokens`
snapshot is available; otherwise those fields are blank.

The UI respects **`prefers-reduced-motion`** and disables canvas animations and
count-up transitions for users who have that system preference set.

---

## Layout

```
CCDashboard/
  cc_dashboard.py          CLI entry point (scan -> build -> open)
  ccdashboard/
    scan.py                build_view_model(config_dir) -> dict
    build.py               generate(view_model, *, out_path, open_browser) -> Path
    web/
      index.html           HTML skeleton with injection placeholders
      styles.css           HUD look-and-feel (glassmorphism, scanlines, arc-reactor)
      app.js               card grid, search/filter, detail drawer
      hud.js               arc-reactor canvas animation + boot sequence
  dist/                    generated output — git-ignored (machine-specific data)
```

`dist/` is listed in `.gitignore`; the generated HTML contains your local config
paths and is never committed.
