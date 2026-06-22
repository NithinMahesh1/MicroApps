# CCDashboard

A futuristic **terminal (TUI)** console for your global Claude Code setup
(`~/.claude`), built with [Textual](https://textual.textualize.io/). Three tabs:

- **Config** — searchable inventory of your skills, agents, memory (`CLAUDE.md`),
  rules, and settings. Shows per-item token costs when a ClaudeBench `count_tokens`
  snapshot exists. Press **Enter** on a row to open that file in **VS Code**.
- **Conversations** — fast full-text search across all your past Claude Code chats
  (`~/.claude/projects/**/*.jsonl`). Press **Enter** on a result to resume it: the
  resume command is copied to your clipboard and your own admin terminal opens
  (Start → "powershell" → Ctrl+Shift+Enter) — paste with **Ctrl+V** to run it.
- **QuizMe** — one Claude-generated question per day from your study notes
  (`Learning\Codebase\**\*.md`), Claude-graded, with SM-2 spaced repetition and a
  daily streak. Needs `ANTHROPIC_API_KEY` (shows a friendly prompt until you set it).

The config inventory reuses ClaudeBench's scanner; the conversation + quiz engines are
their own. All are UI-agnostic, so the UI can change without touching them.

---

## Prerequisites

- **Python 3.11+**
- `pip install -r requirements.txt` (Textual + Rich + pyfiglet + anthropic — pinned, pip-audit-clean)
- **For QuizMe:** set `ANTHROPIC_API_KEY` (Claude generates + grades the questions).
  Without it the other tabs work fully and QuizMe shows a "set the key" prompt.
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
| `1` / `2` / `3` | switch tabs (Config / Conversations / QuizMe) |
| type | search the active tab |
| `/` | jump to the search box |
| `↓` | drop from the search box into the results table |
| `↑` / `↓` | move the row cursor |
| `Enter` | (Config) open the selected component's file in VS Code |
| `Enter` | (Conversations) resume the selected chat — opens your admin terminal; paste with Ctrl+V |
| `ctrl+s` | (QuizMe) submit your answer |
| `ctrl+r` | refresh (re-scan config + re-index conversations) |
| `q` | quit |

---

## Notes

- **Resume** replays your own launch: it copies `cd <dir>; claude --resume <id>`
  (claude referenced by its full path, so an elevated shell still finds it) to the
  clipboard, then presses Win → types `powershell` → Ctrl+Shift+Enter to open the
  same admin terminal you normally use; you finish with **Ctrl+V, Enter**. (Windows
  blocks apps from typing into an elevated window — hence the paste.) It only resumes a
  session present in the index and takes the working directory from the transcript —
  never user input; the cwd/path are single-quote escaped.
- The conversation index reads `~/.claude/projects/**/*.jsonl` read-only; nothing is
  written back. Heavy indexing runs in a background thread; search is debounced and
  matches a precomputed lowercased blob, so it stays instant as chats grow.
- **QuizMe** stores scheduling state **outside the repo** at
  `~/.claude/ccdashboard/quizme.json` (never committed). It needs `ANTHROPIC_API_KEY`;
  until then the tab shows a prompt instead of erroring.

---

## Layout

```
CCDashboard/
  cc_dashboard.py          entry point (parse --config-dir -> launch the TUI)
  ccdashboard/
    scan.py                build_view_model(config_dir) -> config inventory (reuses ClaudeBench)
    conversations.py       index_conversations / search / filter_conversations / launch_resume
    quiz.py                load_cards / SM-2 schedule / gen_question + grade_answer (Claude)
    tui/
      app.py               CCDashboardApp — Header, pyfiglet banner, 3 tabs, Footer
      config_view.py       Config tab (search + DataTable)
      conversations_view.py  Conversations tab (search + DataTable + clipboard resume)
      quiz_view.py         QuizMe tab (question + answer TextArea + Claude grading)
      app.tcss             cyan/teal "Jarvis" theme
  requirements.txt         textual / rich / pyfiglet / anthropic (pinned, pip-audit-clean)
```

The earlier web UI (a self-contained HTML dashboard + local server) was retired in
favour of this TUI; the engine modules (`scan.py`, `conversations.py`) are unchanged.
