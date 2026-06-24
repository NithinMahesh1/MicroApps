# CCDashboard

A futuristic **terminal (TUI)** console for your global Claude Code setup
(`~/.claude`), built with [Textual](https://textual.textualize.io/). Three tabs:

- **Config** — searchable inventory of your skills, agents, memory (`CLAUDE.md`),
  rules, and settings. Shows per-item token costs when a ClaudeBench `count_tokens`
  snapshot exists. Press **Enter** on a row to open that file in **VS Code**.
- **Conversations** — ranked full-text search across all your past Claude Code chats
  (`~/.claude/projects/**/*.jsonl`). Results are ordered by **relevance blended with
  recency** (not just newest-first), so the chat you mean floats to the top — add a
  second title word and it rockets up. Narrow with the **project + date filter row** or
  inline query operators (`project:`/`dir:`, `branch:`, `after:`/`before:`, and
  `"exact phrases"`), and a typo still finds the chat thanks to fuzzy matching. A
  **highlighted preview pane** shows the matching context for the selected row. Press
  **Enter** on a result to resume it: the resume command is copied to your clipboard and
  your own admin terminal opens (Start → "powershell" → Ctrl+Shift+Enter) — paste with
  **Ctrl+V** to run it.
- **QuizMe** — one Claude-generated question per day from your study notes
  (`Learning\Codebase\**\*.md`), Claude-graded, with SM-2 spaced repetition and a
  daily streak. Needs `ANTHROPIC_API_KEY` (shows a friendly prompt until you set it).

The config inventory reuses ClaudeBench's scanner; the conversation search + quiz
engines are their own. The conversation search engine lives in its own UI-agnostic
`ccdashboard/search.py` (parsing + ranking + highlighting), while `conversations.py`
keeps indexing + resume. All are UI-agnostic, so the UI can change without touching them.

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

## Searching conversations

Type to search; results rank by relevance blended with recency. The query box accepts
operators alongside plain terms (plain terms are AND-matched):

| Operator | Effect |
|----------|--------|
| `project:foo` / `dir:foo` | only chats whose working directory contains `foo` |
| `branch:bar` | only chats on a git branch containing `bar` |
| `after:2026-06-01` | chats on/after that date |
| `before:2026-06-30` | chats on/before that date |
| `"exact phrase"` | match the quoted phrase contiguously |

The **project** and **date** dropdowns in the filter row do the same as `project:` and
`after:` for the common cases; an operator you type wins over the dropdown for the same
field. **Fuzzy matching** (stdlib `difflib`, no extra dependency) means a typo like
`permisions` still finds `permissions`, ranked below exact hits. The **preview pane**
under the table shows the matching context for the highlighted row, with your terms
highlighted.

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
  written back. Heavy indexing runs in a background thread; search is debounced and runs
  entirely in memory over precomputed lowercased fields (title/body/project/branch) and
  parsed dates, so ranking, filtering, fuzzy matching, and the preview stay instant as
  chats grow. The search engine itself is UI-agnostic in `ccdashboard/search.py`.
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
    conversations.py       index_conversations / launch_resume (indexing + resume)
    search.py              parse_query / merge_ui_filters / rank / highlight (UI-agnostic)
    quiz.py                load_cards / SM-2 schedule / gen_question + grade_answer (Claude)
    tui/
      app.py               CCDashboardApp — Header, pyfiglet banner, 3 tabs, Footer
      config_view.py       Config tab (search + DataTable)
      conversations_view.py  Conversations tab (filter row + search + DataTable + preview + resume)
      quiz_view.py         QuizMe tab (question + answer TextArea + Claude grading)
      app.tcss             cyan/teal "Jarvis" theme
  tests/                   pytest suite (search/conversations units + a light view smoke)
  requirements.txt         textual / rich / pyfiglet / anthropic (pinned, pip-audit-clean)
  requirements-dev.txt     pytest (pinned, pip-audit-clean)
```

The earlier web UI (a self-contained HTML dashboard + local server) was retired in
favour of this TUI; the engine modules (`scan.py`, `conversations.py`) are unchanged.

---

## Development & tests

```powershell
cd CCDashboard
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests
```

The suite is mostly fast pure-engine unit tests of `search.py` (query parsing, filter
merge, relevance+recency ranking, fuzzy rescue, highlighting) and `conversations.py`
indexing, plus one light Pilot smoke test of the Conversations view.

The conversation-search design — exact ranking weights, query operators, fuzzy
threshold, preview/highlight behaviour, and the filter-row layout — is documented in
full at
[`docs/superpowers/specs/2026-06-24-ccdash-conversation-search-design.md`](docs/superpowers/specs/2026-06-24-ccdash-conversation-search-design.md).

Documented follow-ups (out of scope for now): a persistent, mtime-keyed on-disk index
cache so launch / `ctrl+r` need not re-parse ~300 MB of transcripts, and fully uncapped
/ streaming body search (the per-transcript cap was only raised to 1 MB here).
