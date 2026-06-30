# CCDashboard — Plan & Roadmap

A local "Jarvis" console for your global Claude Code setup (`~/.claude`). Built on a
**UI-agnostic engine** (config inventory + conversation index/search/resume) with a
UI layer on top — so the UI can change without touching the engine.

## Status

### ✅ Done
- [x] Config inventory engine (`ccdashboard/scan.py`) — reuses ClaudeBench's scanner; optional token costs from a ClaudeBench snapshot.
- [x] ~~Self-contained **static** dashboard + Jarvis web UI (reactor HUD, glass panels, scanlines).~~ **Retired** — replaced by the Textual TUI (see below); `build.py` / `server.py` / `web/` removed.
- [x] Conversation engine — index `~/.claude/projects/**/*.jsonl` + **elevated `claude --resume`** in the convo's working dir (`ccdashboard/conversations.py`); ranked search/highlighting split into `ccdashboard/search.py`.
- [x] Local **server mode** (`ccdashboard/server.py`, default of `cc_dashboard.py`) + **Conversations** UI tab (search → branch/cwd/title/snippet → admin resume).
- [x] Registered in AppLauncher (`apps.json`); boot-overlay dismiss fix + faster boot + click-to-skip.

### ⏳ Queued
- [x] **TUI conversion (DONE 2026-06-18)** — UI is now a **Textual TUI** (`ccdashboard/tui/`): Config + Conversations tabs (initial set) over the shared engine, cyan/teal theme + `pyfiglet` banner, admin-resume launched directly. The earlier web UI (static HTML + local server: `build.py`, `server.py`, `web/`) was **retired**. Deps pinned + pip-audit-clean in `requirements.txt`; launcher entry gained a `pip install` prepare step.
- [x] **Memories tab (DONE)** — `ccdashboard/memory.py` + `tui/memory_view.py`: browses/searches per-project Claude auto-memories at `~/.claude/projects/*/memory/*.md` (frontmatter: name/description/type; `MEMORY.md` index skipped). Reuses `ccdashboard/search.py` **verbatim — no engine changes** — by having the `Memory` record expose the same precomputed search fields as `Conversation`; memory-only **Type** facet is a view pre-filter. Filters: Project + Type + Date dropdowns; operators `project:`/`type:`/`after:`/`"phrase"`. Layout: side-by-side list (PROJECT, TYPE, NAME, DESCRIPTION) + reading pane; **Enter opens in VS Code**. Hotkey `3` (QuizMe moved to `4`). No new deps, no API key required; in-app create/edit/delete deferred (YAGNI — edit in VS Code).
- [x] **QuizMe tab (DONE)** — `ccdashboard/quiz.py` + `tui/quiz_view.py`: one Claude-generated question/day from `~/Learning/Codebase/**/*.md` (~201 cards), **Claude-graded** (structured 0–5 + feedback), **SM-2** spaced repetition + daily streak. State stored OUTSIDE the repo at `~/.claude/ccdashboard/quizme.json`. Degrades gracefully (a "set the key" panel) until `ANTHROPIC_API_KEY` is set.
- [x] **Resume via your own terminal (DONE)** — resume copies `cd <dir>; claude --resume <id>` (claude by **full path**, fixing the elevated-PATH "not found" error) to the clipboard and replays Win → "powershell" → Ctrl+Shift+Enter to open your admin terminal; paste to run. Replaces the earlier `Start-Process -Verb RunAs` window.
- [x] **Faster search (DONE)** — precomputed lowercased per-field search text on the frozen `Conversation` + 180 ms input debounce for the TUI (≈6.5× faster per query: ~34 ms → ~5 ms).
- [x] **Ranked search + preview (DONE 2026-06-24)** — CONVERSATIONS search now ranks by **relevance blended with recency** (replacing pure newest-first), with query operators (`project:`/`dir:`, `branch:`, `after:`/`before:`, `"phrases"`), a project/date filter row, stdlib `difflib` fuzzy typo tolerance, and a highlighted **preview pane**. Engine extracted to `ccdashboard/search.py` (`parse_query`/`merge_ui_filters`/`rank`/`highlight`); first `tests/` suite (49 tests) + `requirements-dev.txt`/`pytest.ini`. Spec: `docs/superpowers/specs/2026-06-24-ccdash-conversation-search-design.md`.

### ✅ QuizMe v2 — generated flash-card decks (DONE 2026-06-30)
Turned QuizMe from "one live, throwaway question/day" into a real, persistent
flash-card system over **all** your `.md` notes. Designed + built in the 2026-06-30 chat
via 4 parallel agents over a shared `ccdashboard/models.py` contract. **194 tests green.**

**Generation & storage**
- [x] Generate true Q&A flash cards from **whole notes** (`flashcards.gen_cards`, Claude **Sonnet**, capped — not raw `##` slices), so cards cover substantive content. Fixes the "intro-only `(whole file)` card" that made Claude refuse ("note content is incomplete").
- [x] Persist decks as **Markdown** in app data: `~/.claude/ccdashboard/flashcards/` (outside the repo, never writes into your notes folders; editable in VS Code).
- [x] **Incremental** (re)generation: cache by note content-hash (`deck_is_current`), regenerate only changed notes; manual force-rebuild via `ctrl+b`.
- [x] **Concept-first** prompt for code-implementation guides: tests transferable concepts, allows general tech names (DI, Swagger, EF Core), strips repo-private class names / file paths.

**Quiz flow & scoring**
- [x] **Free practice** (`quiz.select_next_practice`, `ctrl+n`): a "Next card" action keeps serving cards beyond the daily one (most-due → new → upcoming), even after the daily set is done.
- [x] Kept **SM-2 scheduling + daily streak** intact; extra practice advances SM-2 + totals without corrupting the streak.
- [x] **High-score stats** (`Stats` record): status line shows `streak N (best M) · X due · Y answered · Z% accuracy · N cards`.

**Per-card history**
- [x] Each attempt extended from `(date, grade)` to an `Attempt` `{date, question, answer, grade, verdict, feedback}`.
- [x] **Card-history viewer** (`CardHistoryModal`, `ctrl+h`) shows past Q&A + grades for a card to track improvement.

**Notes folders & picker**
- [x] Multiple directories supported (engine + UI) — accumulates across all of them.
- [x] **Fixed the native folder picker**: added **Windows** (PowerShell `FolderBrowserDialog`) + **macOS** (`osascript`) backends; kept Linux (zenity/kdialog/yad/qarma). Platform-ordered, capability-based discovery. (Was Linux-only → "Add folder…" was dead on Windows.)
- [x] Hardened typed **"Add path"** (strips surrounding quotes/whitespace).

**Tests / docs**
- [x] 194 tests: new `tests/test_flashcards.py` (40), `tests/test_quiz.py` (34), `tests/test_folder_picker.py` (12) + updated `test_quiz_config.py`; engine + app integration smokes. README / ARCHITECTURE / PLAN updated.

_Decisions (2026-06-30 chat):_ bulk **generation = Sonnet** (`claude-sonnet-4-6`), **grading = Opus** (`claude-opus-4-8`); **trigger = background build on app launch** with a progress bar + content-hash incremental (cards already on disk are quizzable immediately), plus manual `ctrl+b` rebuild. New engine modules: `ccdashboard/models.py` (shared records) + `ccdashboard/flashcards.py` (deck gen + storage).

### Prereqs / open
- [ ] Set `ANTHROPIC_API_KEY` (the paid key), then restart the terminal — activates the **built** QuizMe (Claude question-gen + grading) **and** flips ClaudeBench from placeholder zeros to real token counts. Until set, QuizMe shows a "set the key" prompt.

## Notes
- The engine is UI-agnostic: `scan.build_view_model`, `conversations.index_conversations/launch_resume`, and `search.parse_query/rank/highlight`. The Textual TUI consumes these functions — only the presentation layer differs.
- QuizMe scheduling state lives OUTSIDE the repo (`~/.claude/ccdashboard/quizme.json`), so there is nothing to git-ignore and no user data can be committed.
