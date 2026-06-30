# CCDashboard — Architecture

A **Textual TUI** over a **UI-agnostic engine**: the engine does the work, the TUI
presents it. See `README.md` for usage; this document covers the engineering design.
The CONVERSATIONS search design (ranking, operators, fuzzy, preview) is specified in
full at
[`docs/superpowers/specs/2026-06-24-ccdash-conversation-search-design.md`](docs/superpowers/specs/2026-06-24-ccdash-conversation-search-design.md).

> An earlier web UI (a self-contained HTML dashboard built by `build.py` + a local
> `server.py`, with assets under `web/`) was **retired** in favour of the TUI. The
> engine modules (`scan.py`, `conversations.py`) are unchanged — only the
> presentation layer was swapped.

---

## Module Layout

```
CCDashboard/
  cc_dashboard.py          Entry point — parses --config-dir, launches the TUI.
  ccdashboard/
    __init__.py
    models.py              Shared immutable records for QuizMe v2: FlashCard, Attempt,
                           CardState, Streak, Stats, QuizState, QuizGrade + make_card_id
                           / content_hash. Pure stdlib; no I/O; no Claude calls — safe
                           to import anywhere without network or SDK.
    scan.py                build_view_model(config_dir) -> config-inventory dict
                           (reuses the sibling ClaudeBench scanner via sys.path).
    conversations.py       index_conversations() / launch_resume() over
                           ~/.claude/projects/**/*.jsonl (indexing + cross-platform resume).
    search.py              UI-agnostic search engine: parse_query / merge_ui_filters /
                           rank (relevance+recency) / highlight — no Textual.
    memory.py              index_memories() / preview() / split_type_operator() over
                           ~/.claude/projects/*/memory/*.md (UI-agnostic; stdlib + rich).
    flashcards.py          Deck generation (Claude Sonnet) + Markdown storage + offline
                           load. gen_cards() / build_decks() / load_decks() /
                           serialize_deck() / parse_deck(). Lazy anthropic import; safe to
                           import without the SDK or network.
    quiz.py                SM-2 scheduling + grading engine (v2). select_today() /
                           select_next_practice() / apply_grade() / review() /
                           bump_streak() / grade_answer() (Claude Opus) + notes-dir
                           config + load_state() / save_state(). Re-exports all
                           models.py types. Lazy anthropic import.
    folder_picker.py       Cross-platform native folder picker — Windows: PowerShell
                           FolderBrowserDialog; macOS: osascript; Linux: zenity/kdialog/
                           yad/qarma. pick_directories(start) -> list[Path].
    editor.py              open_in_editor(path) — open a config file in VS Code (CLI) or
                           the OS default (cross-platform: startfile / xdg-open / open);
                           used by the Config tab's Enter action.
    backup.py              backup_claude(config_dir, backup_dir) -> timestamped copy of
                           ~/.claude; load/save the backup-dir setting (skips locked files).
    tui/
      __init__.py
      app.py               CCDashboardApp (Textual App): Header, pyfiglet banner,
                           TabbedContent[Config, Conversations, Memories, QuizMe], Footer;
                           loads data in a background (@work thread) worker on mount, then
                           kicks a second background worker (_ccd_build_decks) for
                           incremental flash-card generation.
      config_view.py       ConfigView — search Input + DataTable of components;
                           row-select -> editor.open_in_editor(item abs_path).
      conversations_view.py  ConversationsView — project + date filter row, search Input,
                           DataTable, highlighted preview pane; ranks via search.py;
                           row-select -> launch_resume (per-OS: Win clipboard+keystroke /
                           Linux terminal / macOS osascript).
      memory_view.py       MemoriesView — project + type + date dropdowns; debounced
                           search; side-by-side DataTable (left) + reading-pane Static
                           (right); Enter opens the .md in VS Code via editor.open_in_editor.
      quiz_view.py         QuizView — pre-generated card question + answer TextArea +
                           an action row (Submit ctrl+s · Notes Folders… ctrl+o · Next
                           card ctrl+n, free practice) + build progress bar; grading in
                           @work workers; graceful no-key and no-cards panels.
                           GradeResultModal (ModalScreen) — the graded answer shown as an
                           overlay (Next card / Close). CardHistoryModal — a card's full
                           Attempt history (ctrl+h, Esc to close).
      notes_config_screen.py  NotesConfigScreen (ModalScreen) — view/add/remove notes
                           folders via the OS picker (worker thread) or a typed path; Save
                           persists via quiz.save_notes_dirs.
      backup_screen.py     BackupScreen (ModalScreen) — backup-dir field (masked +
                           reveal toggle) + "Back up now"; opened by Config's ctrl+b.
      app.tcss             Cyan/teal "Jarvis" theme.
  tests/                   194-test pytest suite — pure-engine units + light Pilot smokes.
  requirements.txt         textual / rich / pyfiglet / anthropic (pinned, pip-audit-clean).
  requirements-dev.txt     pytest (pinned, pip-audit-clean) — `python -m pytest tests`.
```

---

## Data Flow

```
on_mount ──▶ @work(thread, exclusive): scan.build_view_model(config_dir)
          │                            conversations.index_conversations()
          │                            memory.index_memories()
          │                            flashcards.load_decks()  [offline; no Claude call]
          │                            quiz.load_state()
          └▶ call_from_thread ──▶ ConfigView.load_items(vm)
                                  ConversationsView.load_conversations(convos)
                                  MemoriesView.load_memories(memories)
                                  QuizView.load_quiz(cards, state)
                                  ── then ──▶ _ccd_build_decks() [background, non-exclusive]
                                              flashcards.build_decks(notes_dirs, progress_cb)
                                              (incremental; unchanged note hashes skipped)
                                              ──▶ QuizView.set_build_progress (progress bar)
                                              ──▶ QuizView.on_build_done (reload + present)

search   ──▶ Config tab:        client-side substring filter over name/id/kind/description
         ──▶ Conversations tab: 180 ms-debounced search.parse_query(text) ─▶
                                search.merge_ui_filters(q, project=…, since_days=…) ─▶
                                search.rank(index, q). Ranking blends relevance with
                                recency (replacing pure newest-first), supports the
                                project:/dir:, branch:, after:/before:, "phrase" operators
                                + a visible project/date filter row, and fuzzy typo
                                tolerance (stdlib difflib). The highlighted row drives
                                search.highlight(...) into the preview pane.
         ──▶ Memories tab:      Type/Project/Date dropdowns pre-filter the index ─▶
                                split_type_operator(text) strips any inline `type:` token
                                from the query ─▶ same search.parse_query /
                                merge_ui_filters / rank pipeline (VERBATIM reuse —
                                zero changes to search.py; see Engine Reuse below).

Enter on a conversation row ──▶ ConversationsView._resume (@work thread)
                            ──▶ conversations.launch_resume(session_id, index)
                                (per-OS terminal launch — see the contract below)

Enter on a memory row ──▶ editor.open_in_editor(memory.file_path)
                          (VS Code CLI, or OS default)

QuizMe ──▶ load_quiz presents card.question (from pre-generated deck; no live generation)
           ─▶ user types answer ─▶ ctrl+s ─▶ @work grade_answer (Claude Opus, structured)
           ─▶ apply_grade (SM-2 + Attempt history + streak + Stats) ─▶ save_state
           ─▶ GradeResultModal overlay (Next card advances · Close stays).
           ctrl+n (Next card) ─▶ select_next_practice (free practice, unlimited).
           ctrl+h (History) ─▶ CardHistoryModal — card's full Attempt history.
           ctrl+b (Build deck) ─▶ @work flashcards.build_decks(force=False) ─▶ reload.
           Notes Folders… (ctrl+o) ─▶ NotesConfigScreen ─▶ folder_picker (@work) ─▶
           quiz.save_notes_dirs ─▶ reload cards + trigger build.
```

Indexing 100+ transcripts (and reading the study notes) runs off the UI thread; results
are pushed back with `call_from_thread`. Refresh (`ctrl+r`) re-runs the same worker.

---

## Module Contracts

### `cc_dashboard.py`
Reconfigures stdout/stderr to UTF-8 (Windows cp1252 consoles), puts its own dir on
`sys.path`, parses `--config-dir` (default `~/.claude`), then lazy-imports
`ccdashboard.tui.app.run` and calls it. No business logic.

### `ccdashboard/scan.py` — `build_view_model(config_dir) -> dict`
Adds the repo's `ClaudeBench/` dir to `sys.path` and imports `claudebench.scanner` to
enumerate components. Merges `tokens_always_loaded` / `tokens_invocation` from the
newest `ClaudeBench/snapshots/*.json` whose `tokenizer == "count_tokens"`; otherwise
token fields stay `null`. Returns `{summary: {total, by_kind}, items: [...]}`.
ClaudeBench's `scanner.py` is imported read-only.

### `ccdashboard/conversations.py` (indexing + resume)
- `index_conversations(projects_dir=None) -> list[Conversation]` — globs
  `~/.claude/projects/*/*.jsonl`, parses each transcript into a frozen `Conversation`
  (`session_id`, `cwd`, `git_branch`, `title`, `started_at`, `last_at`,
  `message_count`, `text`, …), sorted by `last_at` desc. Each record also carries
  search fields precomputed once at index time — `title_lc`, `body_lc`, `project_lc`,
  `branch_lc`, `project_name` (the `cwd` leaf), and `last_date` (parsed `date`) — so the
  engine never re-lowercases or re-parses dates per keystroke. (These replaced the old
  single `search_blob`.) The body cap was raised to 1 MB per transcript.
- Search/ranking/highlighting no longer live here — they moved to `search.py` (below).
  `conversations.py` keeps only indexing + resume; its `__main__` smoke test calls
  `search.rank(...)`.
- `launch_resume(session_id, conversations, *, dry_run=False) -> dict` — validates the
  session id against `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, looks up the conversation's
  `cwd` from the index (never the caller), resolves `claude` by full path (so an
  elevated/limited PATH still finds it), and dispatches per OS via `_resume_plan`:
  - **Windows** (`os.name == "nt"`): builds `Set-Location -LiteralPath '<cwd>'; &
    '<claude>' --resume <sid>` (single-quote-escaped), copies it to the clipboard
    (`CF_UNICODETEXT` via ctypes), and replays Win → "powershell" → Ctrl+Shift+Enter
    (`keybd_event`) to open the user's own admin terminal — they paste it (UIPI forbids
    typing into an elevated window, so delivery is via clipboard).
  - **Linux**: spawns (detached — `start_new_session` + `/dev/null` stdio) the first
    installed terminal of `_LINUX_TERMINALS` (`x-terminal-emulator`, `ptyxis`,
    `gnome-terminal`, `kgx`, `konsole`, …, `xterm`) running `bash -lc 'cd <cwd>;
    <claude> --resume <sid>; exec bash'`. Per-emulator flags differ: ptyxis uses
    `--standalone --new-window --`, gnome-terminal/kgx use `--`, kitty/foot take the
    command directly, the rest use `-e`. Raises `RuntimeError` if none is found.
  - **macOS**: runs the same command in Terminal.app via `osascript`.
  cwd + claude path are shell-quoted (`''` for the PowerShell literal, `shlex.quote` on
  POSIX). `dry_run=True` returns the plan (off-Windows it adds `mode`/`platform`/`argv`)
  without launching — used by tests so no keystrokes / UAC / processes fire.

### `ccdashboard/search.py` (UI-agnostic search engine)
Pure stdlib + `rich.text`; depends only on `conversations.Conversation` and knows
nothing about Textual. The CONVERSATIONS view builds a `Query` and calls these:
- `parse_query(raw) -> Query` — parses the search string into a frozen `Query`
  (`terms`, `phrases`, `project`, `branch`, `after`, `before`, `raw`). Operators:
  `"quoted phrases"` (exact, contiguous), `project:`/`dir:` and `branch:` (lc-substring
  filters), `after:YYYY-MM-DD` / `before:YYYY-MM-DD` (date range; unparseable values are
  ignored). Operator keys are case-insensitive; any other token (including an unknown
  `foo:bar`) is a literal AND term.
- `merge_ui_filters(query, *, project=None, since_days=None, now=None) -> Query` —
  folds the visible filter-row dropdowns (project + date preset) into a NEW `Query`,
  but only where the typed query left that field unset (operators win).
- `rank(convos, query, *, now=None) -> list[Conversation]` — applies the hard
  project/branch/date filters, then orders by a blended **relevance + recency** score
  (replacing pure newest-first). Title hits dominate; project/branch/body-frequency and
  a whole-word bonus contribute; recency decays on a 30-day half-life so a much-newer,
  slightly-weaker chat can edge an older one without overtaking a title hit. A term that
  matches no field exactly gets a **fuzzy rescue** (best `difflib.SequenceMatcher` ratio
  ≥ 0.8 over the short fields — never the body), so typos still find the chat ranked
  below exact matches; a term/phrase matching nothing drops the convo. An empty query
  returns the filtered list in `last_at`-desc order. All weights/thresholds are named
  module constants (no magic numbers).
- `highlight(convo, query, *, max_snippets=3, width=160) -> rich.text.Text` and
  `highlight_title(convo, query) -> rich.text.Text` — build the preview-pane renderable
  (metadata header + context windows around the best matches) and the table TITLE cell
  with matched terms styled in the cyan/teal theme (exact `bold #00e5ff`, fuzzy `#7ab8cc`).

### `ccdashboard/memory.py` — `index_memories()` / `preview()` / `split_type_operator()`
UI-agnostic; pure stdlib + `rich.text`, matching the `conversations.py` / `search.py` pattern.
- `Memory` — frozen dataclass with display fields (`name`, `description`, `type`, `body`,
  `project_name`, `project_slug`, `file_path`, `modified`) PLUS search fields that mirror
  `Conversation` exactly: `title`, `title_lc`, `body_lc`, `project_lc`, `branch_lc`,
  `last_at`, `last_date`, `session_id`. The naming is intentional — it lets `search.py`
  rank and highlight `Memory` objects without modification (see Engine Reuse below).
- `index_memories(projects_dir=None) -> list[Memory]` — globs
  `~/.claude/projects/*/memory/*.md`, skips `MEMORY.md`, and returns records sorted
  newest-mtime first. Frontmatter parsing handles two `type` shapes: top-level `type:` and
  `type:` nested under `metadata:` (distinguished from `node_type:` by exact key match).
  Slug→label conversion via `_project_label`: strips the `Path.home()`-derived prefix so
  `…-smart-gift-card` becomes `MyGit-smart-gift-card`, not `card`. This preserves the full
  relative path, disambiguating same-named repos under different parent directories (e.g. a
  worktree under `temp-…`). Nothing machine-specific is hardcoded.
- `preview(memory, query) -> rich.text.Text` — builds the reading-pane renderable (full
  body + highlighted matches), analogous to `search.highlight`.
- `split_type_operator(text) -> tuple[str | None, str]` — extracts an inline `type:` token
  from the query string before it reaches `search.parse_query`; used by `MemoriesView` to
  apply the memory-only Type facet without touching the shared engine.

The TUI companion `ccdashboard/tui/memory_view.py` (`MemoriesView`) is a structural sibling
of `ConversationsView`: project + type + date dropdowns, 180 ms-debounced search,
side-by-side layout (`#mem-table` DataTable left, `#mem-preview` reading-pane `Static`
right, CSS in `app.tcss`). `_ccd_`-prefixed methods/attrs per the project convention.
Enter calls `editor.open_in_editor(memory.file_path)`.

### `ccdashboard/models.py` — shared immutable records
Pure stdlib; no I/O; no Claude calls. All records are frozen + slotted dataclasses
that round-trip through plain dicts / JSON.
- `FlashCard` — one generated Q/A card (`card_id`, `source`, `concept`, `question`,
  `answer`, `note_hash`). `card_id` is a stable 16-hex SHA-1 of `source + question`
  (via `make_card_id`); editing a question yields a new id and fresh SM-2 schedule.
  `FlashCard.create(source, concept, question, answer, note_hash)` computes the id.
- `Attempt` — one graded answer (`date`, `question`, `answer`, `grade 0..5`, `verdict`,
  `feedback`). Full Q/A text is retained (capped at 2 000 chars each) so the history
  modal can show what you answered and got as feedback.
- `CardState` — SM-2 state for one card (`ease`, `interval`, `reps`, `due`,
  `last_grade`, `history: tuple[Attempt, ...]`). `is_new` property returns `True` when
  `due` is empty.
- `Streak` — daily streak (`count`, `longest`, `last_session`).
- `Stats` — lifetime totals (`total_answered`, `total_correct`, `best_day_count`,
  `best_day_date`, `today_count`, `today_date`). `accuracy` property. `record(passed,
  today_iso)` returns a NEW `Stats` with totals and best-day updated (pure).
- `QuizState` — the whole persisted store (`cards: dict[card_id → CardState]`,
  `streak`, `stats`, `version`). `QuizState.from_dict` tolerantly upgrades the v1
  store (no `stats`, flat `[iso, grade]` history entries) on first load.
- `QuizGrade` — transient grade from Claude (`grade 0..5`, `verdict`, `feedback`);
  `passed` property (`grade >= 3`).
- `make_card_id(source, question) -> str` — stable 16-hex SHA-1.
- `content_hash(text) -> str` — 16-hex SHA-256 of note text (used by `flashcards.py`
  for incremental build decisions).

### `ccdashboard/flashcards.py` — deck generation + storage
UI-agnostic; lazy `anthropic` import inside `gen_cards` only (importing the module
never requires the SDK or network).
- `GEN_MODEL = "claude-sonnet-4-6"` — the generation model.
- Storage: `flashcards_dir() -> Path` (`~/.claude/ccdashboard/flashcards/`);
  `deck_path(source) -> Path` — deterministic collision-resistant slug (`/` → `__`).
- Markdown round-trip: `serialize_deck(deck) -> str` / `parse_deck(text) -> Deck`.
  Format: a leading `<!-- ccd-flashcards v=2 source="…" note_hash="…" model="…"
  generated="…" -->` comment, then `## Concept: …` / `**Q:** …` / `**A:** …` blocks.
- Atomic I/O: `save_deck(deck) -> Path` (temp-file + `os.replace`);
  `load_deck(path) -> Deck | None`; `load_decks() -> list[FlashCard]` — flat de-duped
  list from all `*.md` in `flashcards_dir()`. **Offline startup call; no Claude.**
- `gen_cards(source, note_text, note_hash) -> list[FlashCard]` — calls Claude Sonnet
  via `messages.parse` structured output to generate 3–8 transferable-concept cards.
  The system prompt instructs it to generalise away private identifiers (project class
  names, internal package names, repo-specific paths). Raises `FlashcardsUnavailable`
  when key/SDK missing.
- `deck_is_current(source, note_hash) -> bool` — compares stored hash to skip notes
  that haven't changed.
- `build_decks(notes_dirs, progress_cb, force) -> BuildResult` — incremental walk:
  reads each `*.md`, content-hashes it, skips if hash current or note `< 200` chars,
  calls `gen_cards` for changed/new notes, saves deck, fires
  `progress_cb(done, total, source)`. Per-note failures never abort the overall build.
  Returns `BuildResult(total, generated, skipped, failed, cards)`.
- `regenerate_note(notes_dirs, source) -> list[FlashCard]` — force-regenerates one
  note's deck (used by the future per-card rebuild command).

### `ccdashboard/quiz.py` — SM-2 scheduling, grading, selection, state I/O (v2)
UI-agnostic; lazy `anthropic` import inside `grade_answer` only. Re-exports all
`models.py` types so `quiz.FlashCard`, `quiz.QuizState`, etc. resolve for the TUI.
- `QUIZ_MODEL = "claude-opus-4-8"` — the grading model.
- Notes-dir config (OUTSIDE the repo): `load_notes_dirs()` resolves
  `~/.claude/ccdashboard/config.json` (`notesDirs`) → `CCDASHBOARD_NOTES_DIR` env →
  `~/Learning/Codebase`; `save_notes_dirs(dirs)` persists the list atomically.
- `load_state() / save_state()` — round-trippable JSON written atomically OUTSIDE the
  repo at `~/.claude/ccdashboard/quizme.json`.
- SM-2 math (pure): `review(state, quality, today) -> CardState` — interval uses the
  OLD ease; EF updated every review and floored at 1.3; quality `< 3` resets reps to 0
  and interval to 1. Returns a NEW `CardState` (no mutation; no `Attempt` appended here).
- `select_today(state, cards, today) -> FlashCard | None` — most-overdue first (lowest
  ease breaks ties), else brand-new (source order), else soonest upcoming. Does NOT
  check the daily gate — callers use `answered_today` for that.
- `select_next_practice(state, cards, today, exclude_ids) -> FlashCard | None` — same
  priority order but skips `exclude_ids` (session-seen set), enabling unlimited free
  practice after the daily card.
- `apply_grade(state, card, grade, answer, today) -> QuizState` — single transaction:
  appends `Attempt` to the card's history, advances SM-2 via `review()`, bumps
  `Streak`, updates `Stats`. Returns a NEW `QuizState` (no mutation).
- `grade_answer(card, answer) -> QuizGrade` — grades a free-text answer against the
  card's stored `question` and `answer` via Claude Opus (`messages.parse` structured
  output, SM-2 0..5 scale). Raises `QuizUnavailable` when key unset.
- `due_count(state, cards, today) -> int` / `answered_today(streak, today) -> bool` /
  `bump_streak(streak, today) -> Streak` — pure helpers used by the status line.

### `ccdashboard/folder_picker.py` — cross-platform OS folder picker
Pure stdlib (subprocess); no Textual. `pick_directories(start=None) -> list[Path]`
opens the first available native picker:
- **Windows** — `powershell`/`pwsh` running a `FolderBrowserDialog` script (`-STA`
  thread model; WinForms).
- **macOS** — `osascript` running `choose folder with multiple selections allowed`.
- **Linux / POSIX** — `zenity`, `kdialog`, `yad`, `qarma` (GTK/Qt; multi-select where
  supported).
Returns the chosen dirs (or `[]` on cancel); raises `PickerUnavailable` when no tool
is found. Backend selection is capability-based (`shutil.which`) — works on any
machine regardless of OS version or distro. MUST be called from a worker thread (it
blocks on the dialog). Used by `NotesConfigScreen` to let the user choose QuizMe's
notes folder(s).

### `ccdashboard/backup.py` — full-tree backup of `~/.claude`
Pure stdlib; no Textual. Persists the backup directory as a user setting and copies the
whole config dir into a timestamped folder.
- `DEFAULT_BACKUP_DIR` — default backup root (`~/Backup Claude Code`).
- `settings_path() -> Path` — the settings file, `~/.claude/ccdashboard/settings.json`
  (outside the repo, never committed).
- `load_settings(path=None) -> dict` / `save_settings(settings, path=None)` —
  round-trippable JSON read/write (atomic), defaulting to `settings_path()`.
- `get_backup_dir() -> str` / `set_backup_dir(path)` — read / update the persisted backup
  directory (falls back to `DEFAULT_BACKUP_DIR` when unset).
- `backup_claude(config_dir, backup_dir, *, dry_run=False) -> {dest, files, bytes, skipped, errors}`
  — copies `config_dir` into `dest = <backup_dir>/claude-backup-<timestamp>` (timestamp
  `YYYY-MM-DD_HH-MM-SS`); recursion-guarded (raises `ValueError` / refuses the whole backup if the backup dir
  resolves inside the config dir) and robust to locked/unreadable files (collected in `skipped` / `errors`,
  never fatal). `dry_run=True` returns the plan without copying.

The TUI companion `ccdashboard/tui/backup_screen.py` (`BackupScreen`, a Textual
`ModalScreen`) is opened by the Config tab's `ctrl+b`: it shows the backup directory
(masked, with a reveal toggle) and a **Back up now** button, then calls `backup_claude`.

### `ccdashboard/tui/app.py` — `CCDashboardApp(App)` / `run(config_dir)`
`CSS_PATH = "app.tcss"`. Composes Header (clock), a `pyfiglet` banner Static, a
`TabbedContent` with the Config, Conversations, Memories, and QuizMe panes, and a Footer.
Bindings: `q` quit, `ctrl+r` refresh, `1`/`2`/`3`/`4` switch tabs, `/` focus the active
tab's search. On tab activation/load it calls `_ccd_active_view().focus_search()` so
focus lands in the content (every view implements `focus_search()`). On mount it kicks off
a background `@work(exclusive=True)` loader that calls `flashcards.load_decks()` +
`quiz.load_state()` (offline) alongside the config/conversation/memory indexing, populates
all views via `call_from_thread`, then starts a second `@work(exclusive=False)` worker
(`_ccd_build_decks`) to run the incremental deck build in the background. `run(config_dir)`
is the entry point used by `cc_dashboard.py`.

---

## Textual Gotchas Honoured

- Instance attributes are prefixed `_ccd_*` and the table-fill method is
  `_ccd_render` — never shadow Textual internals (`_render`, `_registry`, …). (A method
  literally named `_render` shadows `Widget._render()` and crashes rendering.)
- Heavy work (indexing, resume launch) runs in `@work(thread=True)` workers; UI updates
  from those threads go through `call_from_thread`.

---

## Engine Reuse & Testability

`scan.py` imports the sibling `claudebench` package (ClaudeBench's scanner) by adding
`../ClaudeBench` to `sys.path`; ClaudeBench remains a fully independent CLI.
`models.py` is pure stdlib with no I/O. `flashcards.py`, `conversations.py`,
`search.py`, `memory.py`, and `quiz.py` are pure stdlib (`flashcards.py` and `quiz.py`
lazy-import `anthropic` only inside their Claude-backed functions; `search.py` and
`memory.py` also use `rich.text`); `flashcards.py` and `quiz.py` each ship a
`__main__` offline smoke test. The engine modules are import-safe and
headless-testable, which is how the TUI is smoke-tested (Textual's `run_test()` pilot).

**`search.py` is reused verbatim for Memories — zero changes to the engine.** `Memory`
exposes the exact field names (`title`, `title_lc`, `body_lc`, `project_lc`, `branch_lc`,
`last_at`, `last_date`, `session_id`) that `search.parse_query` / `rank` /
`highlight_title` already read, so the engine operates on `Memory` objects identically to
`Conversation` objects. The memory-only **Type** facet is applied as a view-level
pre-filter in `MemoriesView`, and `split_type_operator` strips any inline `type:` token
before the text reaches the parser — so the shared engine never encounters a
memory-specific concept. As a consequence, the existing Conversations search behavior is
provably unchanged, and the search/conversations test suites stay green without modification.

The pytest suite under `tests/` (**194 tests**; `python -m pytest tests`) covers:
`search.py` (`parse_query` / `merge_ui_filters` / `rank` / `highlight`),
`conversations.py` indexing, `flashcards.py` (deck generation, Markdown round-trip,
incremental build, `deck_is_current`), `quiz.py` (SM-2 math, streak, stats,
`select_today` / `select_next_practice` / `apply_grade`), and `folder_picker.py`
(cross-platform tool detection and argument building), plus light Pilot smoke tests
of the TUI. New test modules added in v2: `tests/test_flashcards.py`,
`tests/test_quiz.py`, `tests/test_folder_picker.py`.

### Documented follow-ups
- A persistent, mtime-keyed on-disk index cache so launch / `ctrl+r` need not re-parse
  ~300 MB of transcripts — the biggest future scalability win.
- Fully uncapped / streaming body search (the per-transcript cap was only raised to
  1 MB here).

---

## AppLauncher Integration

Registered in the root `apps.json` (`id: cc-dashboard`, `launchMode: console`). The
entry has a `prepare` step (`pip install -r requirements.txt`) so the launcher installs
Textual before the first run. The manifest entry is the sole integration point — no
launcher code changes.
