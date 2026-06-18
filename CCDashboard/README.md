# CCDashboard

A futuristic **terminal (TUI)** console for your global Claude Code setup
(`~/.claude`), built with [Textual](https://textual.textualize.io/). Two tabs:

- **Config** — searchable inventory of your skills, agents, memory (`CLAUDE.md`),
  rules, and settings. Shows per-item token costs when a ClaudeBench `count_tokens`
  snapshot exists.
- **Conversations** — full-text search across all your past Claude Code chats
  (`~/.claude/projects/**/*.jsonl`). Press **Enter** on a result to resume it in an
  **elevated PowerShell** (`claude --resume <id>` in that chat's working directory).

The config inventory reuses ClaudeBench's scanner; the conversation engine is its own.
Both are UI-agnostic, so the UI can change without touching them.

---

## Prerequisites

- **Python 3.11+**
- `pip install -r requirements.txt` (Textual + Rich + pyfiglet — pinned, pip-audit-clean)
- **Optional:** run a ClaudeBench `snapshot` first to populate the token-cost columns.
  Without one, the Config tab still lists everything; token fields show `—`.

```powershell
# One-time (optional) — capture token costs so the Config tab can display them
cd ClaudeBench
pip install -r requirements.txt
python claude_bench.py snapshot --label before-session
```

---

## Run

```powershell
cd CCDashboard
pip install -r requirements.txt
python cc_dashboard.py                       # or launch "CC Dashboard" from AppLauncher
python cc_dashboard.py --config-dir <path>   # scan a different config dir
```

---

## Keys

| Key | Action |
|-----|--------|
| `1` / `2` | switch tabs (Config / Conversations) |
| type | search the active tab |
| `↑` / `↓` | move the row cursor |
| `Enter` | (Conversations) resume the selected chat — fires a UAC prompt, opens an admin PowerShell |
| `ctrl+r` | refresh (re-scan config + re-index conversations) |
| `q` | quit |

---

## Notes

- Resume is safe: it only resumes a session present in the index, validates the
  session id, and takes the working directory from the **transcript** — never from
  user input. It writes a small `.ps1` and elevates a PowerShell with
  `Start-Process -Verb RunAs`.
- The conversation index reads `~/.claude/projects/**/*.jsonl` read-only; nothing is
  written back. Heavy indexing runs in a background thread so the UI stays responsive.
- **QuizMe** — a daily, spaced-repetition quiz drawn from your `Learning\Codebase`
  notes (Claude-generated questions, Claude-graded answers) — is planned; see `PLAN.md`.

---

## Layout

```
CCDashboard/
  cc_dashboard.py          entry point (parse --config-dir -> launch the TUI)
  ccdashboard/
    scan.py                build_view_model(config_dir) -> config inventory (reuses ClaudeBench)
    conversations.py       index_conversations / search / launch_resume
    tui/
      app.py               CCDashboardApp — Header, pyfiglet banner, tabs, Footer
      config_view.py       Config tab (search + DataTable)
      conversations_view.py  Conversations tab (search + DataTable + admin resume)
      app.tcss             cyan/teal "Jarvis" theme
  requirements.txt         textual / rich / pyfiglet (pinned, pip-audit-clean)
```

The earlier web UI (a self-contained HTML dashboard + local server) was retired in
favour of this TUI; the engine modules (`scan.py`, `conversations.py`) are unchanged.
