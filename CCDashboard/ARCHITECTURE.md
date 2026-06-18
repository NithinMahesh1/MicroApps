# CCDashboard — Architecture

Python app in the MicroApps mono-repo that generates a self-contained Jarvis HUD
dashboard for the user's global Claude Code configuration (`~/.claude/`).
See `README.md` for user-facing usage; this document covers the engineering design.

---

## Pipeline: scan -> build -> open

```
~/.claude/
    |
    v
ccdashboard/scan.py      build_view_model(config_dir)
    |                    - imports claudebench.scanner for the item inventory
    |                    - merges token costs from newest ClaudeBench snapshot
    |
    v                    view_model dict (window.CCDASH_DATA shape)
    |
    v
ccdashboard/build.py     generate(view_model, *, out_path, open_browser)
    |                    - reads web/{index.html,styles.css,app.js,hud.js}
    |                    - inlines CSS + JS + JSON data into a single HTML file
    |                    - writes dist/dashboard.html
    |
    v
webbrowser.open(out_path)   (skipped with --no-open)
```

The output is a fully self-contained file — no network requests, no server, no
external assets. Opening it later (offline) shows the same result.

---

## Module Layout

```
CCDashboard/
  cc_dashboard.py          CLI entry point + argparse
  ccdashboard/
    __init__.py
    scan.py                build_view_model
    build.py               generate
    web/
      index.html           HTML skeleton
      styles.css           visual theme
      app.js               UI logic
      hud.js               arc-reactor canvas + boot
  dist/                    generated output (git-ignored)
```

---

## Module Contracts

### `cc_dashboard.py`

Parses CLI arguments (`--config-dir`, `--out`, `--no-open`), calls
`scan.build_view_model`, then `build.generate`. Returns exit code 0 on success,
non-zero on error. No business logic lives here.

### `ccdashboard/scan.py` — `build_view_model(config_dir) -> dict`

1. Adds the repo's `ClaudeBench/` directory to `sys.path` using
   `Path(__file__).parents[2] / "ClaudeBench"` and imports
   `from claudebench import scanner`.
2. Calls `scanner.walk(config_dir)` to get the full component list.
3. Looks for the newest `ClaudeBench/snapshots/*.json` (by filename timestamp).
   If found and its `tokenizer` field is `"count_tokens"`, merges
   `tokens_always_loaded` and `tokens_invocation` into each matching item by
   `(kind, id)`. Sets `has_tokens = True`; otherwise `has_tokens = False` and
   token fields remain `null`.
4. Returns the `window.CCDASH_DATA` dict (see Data Contract below).

ClaudeBench's `scanner.py` is imported read-only; CCDashboard never modifies it.

### `ccdashboard/build.py` — `generate(view_model, *, out_path, open_browser) -> Path`

Reads the four source assets from `ccdashboard/web/`. Builds the final HTML by
replacing four placeholder tokens inside `index.html`:

| Placeholder | Replaced with |
|---|---|
| `/*__CCDASH_CSS__*/` | Full content of `styles.css` |
| `/*__CCDASH_DATA__*/` | `JSON.stringify(view_model)` — injected as `window.CCDASH_DATA = ...;` |
| `/*__CCDASH_HUD_JS__*/` | Full content of `hud.js` |
| `/*__CCDASH_APP_JS__*/` | Full content of `app.js` |

Writes to `out_path` (creating parent directories if needed). If `open_browser` is
true, calls `webbrowser.open(out_path.as_uri())`. Returns the resolved `Path`.

---

## Data Contract — `window.CCDASH_DATA`

```jsonc
{
  "generated_at": "2026-06-18T14:30:00Z",   // ISO 8601
  "config_dir": "C:/Users/user/.claude",
  "has_tokens": true,                        // false when no count_tokens snapshot exists
  "summary": {
    "total": 24,
    "by_kind": {
      "skill": 12,
      "agent": 4,
      "memory": 1,
      "rule": 4,
      "setting": 1,
      "mcp": 2
    }
  },
  "items": [
    {
      "kind": "skill",                       // skill|agent|memory|rule|setting|mcp
      "id": "commit-message",               // filename stem (from scanner)
      "name": "commit-message",
      "description": "Generates a concise...",
      "path": "C:/Users/user/.claude/skills/commit-message.md",
      "size_bytes": 1842,
      "modified": "2026-05-10T09:12:00Z",   // ISO 8601
      "preview": "# Commit Message\n...",   // first ~500 chars of file content
      "tokens_always_loaded": 312,          // null when has_tokens is false
      "tokens_invocation": 1530             // null when not applicable or no snapshot
    }
    // ... one entry per config item
  ]
}
```

`items` is sorted by `kind` then `name` (stable, matches ClaudeBench scanner order).
All mutations return new dicts; nothing is modified in-place.

---

## DOM / Asset Split

### `web/index.html`

Minimal HTML5 skeleton. Contains a `<style>` block with the
`/*__CCDASH_CSS__*/` placeholder, a `<script>` block declaring
`window.CCDASH_DATA = /*__CCDASH_DATA__*/;`, followed by a `<script>` block with
`/*__CCDASH_HUD_JS__*/`, and a final `<script>` block with `/*__CCDASH_APP_JS__*/`.
The `<body>` has the arc-reactor `<canvas>` element, a `#summary` container for the
six kind panels, a `#search-bar` input, `#kind-filters` chip row, `#card-grid`
container, and a `#detail-drawer` overlay panel.

### `web/styles.css`

- Dark background (`#0a0e1a`), blue-cyan (`#00c8ff`) primary accent.
- Glassmorphism panels: `backdrop-filter: blur`, semi-transparent borders.
- Scanlines overlay via a repeating-linear-gradient pseudo-element.
- Card hover glow, kind-badge colour map, drawer slide-in transition.
- `@media (prefers-reduced-motion: reduce)` block disables all animations and
  transitions (canvas, count-up, scanlines).

### `web/app.js`

Runs after `hud.js` boots. Reads `window.CCDASH_DATA` and:
- Renders the six summary panels with count-up animation (integer step per frame).
- Renders the card grid from `items`; each card shows kind badge, name,
  description truncated to two lines, size, and modified date.
- Wires the search input (debounced, filters by `name + description + path`) and
  kind-filter chips (toggleable; multiple kinds can be active simultaneously).
- Click on any card opens the detail drawer, populating name, kind, path, size,
  modified, tokens (skipped if `has_tokens` is false), description, and `<pre>`
  preview. Click outside the drawer or press Escape to close.

### `web/hud.js`

- Draws the arc-reactor on the `<canvas>` element: concentric rings, rotating arc
  segments, pulsing core glow, all via `requestAnimationFrame`.
- Runs a boot sequence on page load: briefly shows a "SCANNING CONFIG..." overlay
  with a progress bar, then transitions to the main dashboard view.
- Exports nothing; side-effects only. Respects `prefers-reduced-motion` by skipping
  animation frames and rendering a static reactor image instead.

---

## ClaudeBench Reuse

CCDashboard treats ClaudeBench as a library, not a subprocess:

```python
# ccdashboard/scan.py
import sys
from pathlib import Path

repo_root = Path(__file__).parents[2]          # .../MicroApps/
sys.path.insert(0, str(repo_root / "ClaudeBench"))

from claudebench import scanner                # walk() -> list[Component]
```

`parents[2]` resolves: `scan.py` -> `ccdashboard/` -> `CCDashboard/` -> `MicroApps/`.

Token-cost merge logic reads the newest `ClaudeBench/snapshots/*.json` directly
(stdlib `json.load`). Only snapshots where `tokenizer == "count_tokens"` are used;
empirical (`claude-p-fallback`) snapshots do not contribute token data to the
dashboard. The snapshot file is never written or modified.

ClaudeBench remains a fully independent CLI. Running
`python ClaudeBench/claude_bench.py list` or `snapshot` works identically whether
or not CCDashboard exists.

---

## Self-Contained / Offline Design

- All CSS, JavaScript, and JSON data are inlined into a single `dashboard.html`
  file. No CDN, no `<link>` tags, no `<script src>` references.
- The file can be opened at any time (even offline) and will display the config
  state from when it was generated. To refresh, re-run `cc_dashboard.py`.
- Python stdlib only (`pathlib`, `json`, `webbrowser`, `argparse`, `datetime`).
  No `pip install` required.

---

## `dist/` is Git-Ignored

`CCDashboard/dist/` is listed in the repo `.gitignore`. The generated HTML embeds
absolute local paths and is machine-specific; committing it would expose personal
config structure. To share a snapshot, export the HTML file manually.

---

## AppLauncher Integration

CCDashboard is registered in the root `apps.json` so it appears in the AppLauncher
TUI alongside the other apps. The entry uses the `console` launch mode so AppLauncher
opens a terminal window, runs the command, and the browser opens automatically.

```json
{
  "id": "cc-dashboard",
  "name": "CCDashboard",
  "description": "Jarvis HUD dashboard for your ~/.claude/ config",
  "stack": "python",
  "cwd": "CCDashboard",
  "launch": "python cc_dashboard.py",
  "launchMode": "console"
}
```

No launcher code changes are needed; the manifest entry is the sole integration point.
