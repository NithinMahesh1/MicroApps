# CCDashboard — Plan & Roadmap

A local "Jarvis" console for your global Claude Code setup (`~/.claude`). Built on a
**UI-agnostic engine** (config inventory + conversation index/search/resume) with a
UI layer on top — so the UI can change without touching the engine.

## Status

### ✅ Done
- [x] Config inventory engine (`ccdashboard/scan.py`) — reuses ClaudeBench's scanner; optional token costs from a ClaudeBench snapshot.
- [x] ~~Self-contained **static** dashboard + Jarvis web UI (reactor HUD, glass panels, scanlines).~~ **Retired** — replaced by the Textual TUI (see below); `build.py` / `server.py` / `web/` removed.
- [x] Conversation engine (`ccdashboard/conversations.py`) — index `~/.claude/projects/**/*.jsonl`, full-text search, **elevated `claude --resume`** in the convo's working dir.
- [x] Local **server mode** (`ccdashboard/server.py`, default of `cc_dashboard.py`) + **Conversations** UI tab (search → branch/cwd/title/snippet → admin resume).
- [x] Registered in AppLauncher (`apps.json`); boot-overlay dismiss fix + faster boot + click-to-skip.

### ⏳ Queued
- [x] **TUI conversion (DONE 2026-06-18)** — UI is now a **Textual TUI** (`ccdashboard/tui/`): Config + Conversations tabs over the shared engine, cyan/teal theme + `pyfiglet` banner, admin-resume launched directly. The earlier web UI (static HTML + local server: `build.py`, `server.py`, `web/`) was **retired**. Deps pinned + pip-audit-clean in `requirements.txt`; launcher entry gained a `pip install` prepare step.
- [x] **QuizMe tab (DONE)** — `ccdashboard/quiz.py` + `tui/quiz_view.py`: one Claude-generated question/day from `C:\Users\NithinMahesh\Learning\Codebase\**\*.md` (~201 cards), **Claude-graded** (structured 0–5 + feedback), **SM-2** spaced repetition + daily streak. State stored OUTSIDE the repo at `~/.claude/ccdashboard/quizme.json`. Degrades gracefully (a "set the key" panel) until `ANTHROPIC_API_KEY` is set.
- [x] **Resume via your own terminal (DONE)** — resume copies `cd <dir>; claude --resume <id>` (claude by **full path**, fixing the elevated-PATH "not found" error) to the clipboard and replays Win → "powershell" → Ctrl+Shift+Enter to open your admin terminal; paste to run. Replaces the earlier `Start-Process -Verb RunAs` window.
- [x] **Faster search (DONE)** — precomputed lowercased `search_blob` on the frozen `Conversation` + 180 ms input debounce + snippet-free `filter_conversations()` for the TUI (≈6.5× faster per query: ~34 ms → ~5 ms).

### Prereqs / open
- [ ] Set `ANTHROPIC_API_KEY` (the paid key), then restart the terminal — activates the **built** QuizMe (Claude question-gen + grading) **and** flips ClaudeBench from placeholder zeros to real token counts. Until set, QuizMe shows a "set the key" prompt.

## Notes
- The engine is UI-agnostic: `scan.build_view_model`, `conversations.index_conversations/search/launch_resume`. A web UI and a future Textual TUI both consume the same functions — only the presentation layer differs.
- QuizMe scheduling state lives OUTSIDE the repo (`~/.claude/ccdashboard/quizme.json`), so there is nothing to git-ignore and no user data can be committed.
