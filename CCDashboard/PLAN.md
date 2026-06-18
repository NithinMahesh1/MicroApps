# CCDashboard — Plan & Roadmap

A local "Jarvis" console for your global Claude Code setup (`~/.claude`). Built on a
**UI-agnostic engine** (config inventory + conversation index/search/resume) with a
UI layer on top — so the UI can change without touching the engine.

## Status

### ✅ Done
- [x] Config inventory engine (`ccdashboard/scan.py`) — reuses ClaudeBench's scanner; optional token costs from a ClaudeBench snapshot.
- [x] Self-contained **static** dashboard (`build.py`, `cc_dashboard.py --static`) + Jarvis web UI (reactor HUD, glass panels, scanlines).
- [x] Conversation engine (`ccdashboard/conversations.py`) — index `~/.claude/projects/**/*.jsonl`, full-text search, **elevated `claude --resume`** in the convo's working dir.
- [x] Local **server mode** (`ccdashboard/server.py`, default of `cc_dashboard.py`) + **Conversations** UI tab (search → branch/cwd/title/snippet → admin resume).
- [x] Registered in AppLauncher (`apps.json`); boot-overlay dismiss fix + faster boot + click-to-skip.

### ⏳ Queued
- [ ] **TUI conversion** — re-implement the UI as a **Textual TUI** (like AppLauncher / MeetingTracker), reusing the existing engine. Futuristic styling within terminal limits (cyan/teal theme, glowing borders, a `pyfiglet` banner, panels/tables); admin-resume launched directly (no local server needed). Decision pending: replace the web UI vs keep it as an option.
- [ ] **QuizMe tab/screen** — one quiz question per calendar day drawn from `C:\Users\NithinMahesh\Learning\Codebase\**\*.md`.
  - [ ] **Claude-generated questions + Claude-graded answers** → requires `ANTHROPIC_API_KEY`.
  - [ ] Spaced repetition — mix new questions with due reviews so old material resurfaces and is retained.
  - [ ] Git-ignored history store (date asked, source note, your result/grade); one-per-day gate; streak.

### Prereqs / open
- [ ] Set `ANTHROPIC_API_KEY` (the paid key), then restart the terminal — unlocks QuizMe **and** flips ClaudeBench from placeholder zeros to real token counts.

## Notes
- The engine is UI-agnostic: `scan.build_view_model`, `conversations.index_conversations/search/launch_resume`. A web UI and a future Textual TUI both consume the same functions — only the presentation layer differs.
- `dist/` and the (future) quiz history are git-ignored (machine-specific data).
