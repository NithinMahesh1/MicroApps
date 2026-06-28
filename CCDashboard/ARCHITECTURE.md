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
    scan.py                build_view_model(config_dir) -> config-inventory dict
                           (reuses the sibling ClaudeBench scanner via sys.path).
    conversations.py       index_conversations() / launch_resume() over
                           ~/.claude/projects/**/*.jsonl (indexing + cross-platform resume).
    search.py              UI-agnostic search engine: parse_query / merge_ui_filters /
                           rank (relevance+recency) / highlight — no Textual.
    quiz.py                load_all_cards() (split notes from configurable folder(s) into
                           SM-2 cards) / notes-dir config / review() + selection /
                           gen_question() + grade_answer() (Claude).
    folder_picker.py       Native OS folder picker (zenity/kdialog/yad) — choose notes dirs.
    editor.py              open_in_editor(path) — open a config file in VS Code (CLI) or
                           the OS default (cross-platform: startfile / xdg-open / open);
                           used by the Config tab's Enter action.
    backup.py              backup_claude(config_dir, backup_dir) -> timestamped copy of
                           ~/.claude; load/save the backup-dir setting (skips locked files).
    tui/
      __init__.py
      app.py               CCDashboardApp (Textual App): Header, pyfiglet banner,
                           TabbedContent[Config, Conversations, QuizMe], Footer; loads
                           data in a background (@work thread) worker on mount.
      config_view.py       ConfigView — search Input + DataTable of components;
                           row-select -> editor.open_in_editor(item abs_path).
      conversations_view.py  ConversationsView — project + date filter row, search Input,
                           DataTable, highlighted preview pane; ranks via search.py;
                           row-select -> launch_resume (per-OS: Win clipboard+keystroke /
                           Linux terminal / macOS osascript).
      quiz_view.py         QuizView — question Static + answer TextArea + Submit + Notes
                           folders… (ctrl+o); gen/grade in @work workers; graceful no-key
                           and no-notes panels.
      notes_config_screen.py  NotesConfigScreen (ModalScreen) — view/add/remove notes
                           folders via the OS picker (worker thread) or a typed path; Save
                           persists via quiz.save_notes_dirs.
      backup_screen.py     BackupScreen (ModalScreen) — backup-dir field (masked +
                           reveal toggle) + "Back up now"; opened by Config's ctrl+b.
      app.tcss             Cyan/teal "Jarvis" theme.
  tests/                   First pytest suite — pure-engine units + a light Pilot smoke.
  requirements.txt         textual / rich / pyfiglet / anthropic (pinned, pip-audit-clean).
  requirements-dev.txt     pytest (pinned, pip-audit-clean) — `python -m pytest tests`.
```

---

## Data Flow

```
on_mount ──▶ @work(thread, exclusive): scan.build_view_model(config_dir)
          │                            conversations.index_conversations()
          │                            quiz.load_all_cards() + quiz.load_state()
          └▶ call_from_thread ──▶ ConfigView.load_items(vm)
                                  ConversationsView.load_conversations(convos)
                                  QuizView.load_quiz(cards, state)

search   ──▶ Config tab:        client-side substring filter over name/id/kind/description
         ──▶ Conversations tab: 180 ms-debounced search.parse_query(text) ─▶
                                search.merge_ui_filters(q, project=…, since_days=…) ─▶
                                search.rank(index, q). Ranking blends relevance with
                                recency (replacing pure newest-first), supports the
                                project:/dir:, branch:, after:/before:, "phrase" operators
                                + a visible project/date filter row, and fuzzy typo
                                tolerance (stdlib difflib). The highlighted row drives
                                search.highlight(...) into the preview pane.

Enter on a conversation row ──▶ ConversationsView._resume (@work thread)
                            ──▶ conversations.launch_resume(session_id, index)
                                (per-OS terminal launch — see the contract below)

QuizMe ──▶ load_quiz picks today's card ─▶ @work gen_question (Claude) ─▶ answer ─▶
           ctrl+s ─▶ @work grade_answer (Claude, structured) ─▶ apply_grade (SM-2)
           ─▶ save_state.
           Notes folders… (ctrl+o) ─▶ NotesConfigScreen ─▶ folder_picker (@work) ─▶
           quiz.save_notes_dirs ─▶ reload cards.
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
  - **Linux**: spawns the first installed terminal (`x-terminal-emulator`,
    `gnome-terminal` [uses `--`], `konsole`, …, `xterm`) running `bash -lc 'cd <cwd>;
    <claude> --resume <sid>; exec bash'`; raises `RuntimeError` if none is found.
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

### `ccdashboard/quiz.py`
UI-agnostic, pure stdlib except a LAZY `anthropic` import inside the two Claude calls
(so importing the module — and the TUI — never needs the SDK or network).
- `load_cards(notes_dir=None) -> list[Card]` — split every `*.md` under one folder into
  frozen `Card`s (per `##`/`###` section, else whole file).
- `load_all_cards(notes_dirs=None) -> list[Card]` — cards from every configured folder
  (deduped by id); `notes_dirs` defaults to `load_notes_dirs()`.
- Notes-dir config (OUTSIDE the repo): `load_notes_dirs()` resolves
  `~/.claude/ccdashboard/config.json` (`notesDirs`) → `CCDASHBOARD_NOTES_DIR` env →
  `~/Learning/Codebase`; `save_notes_dirs(dirs)` persists the list (managed by the UI).
- SM-2 scheduling (pure): `review(state, quality, today)`, `select_today(...)`,
  `bump_streak(...)`, `apply_grade(...)` — all return NEW immutable state.
- `load_state()/save_state()` — round-trippable JSON written atomically OUTSIDE the repo
  at `~/.claude/ccdashboard/quizme.json`.
- `gen_question(card) -> str` / `grade_answer(card, q, ans) -> QuizGrade` — Claude
  (`claude-opus-4-8`; `grade_answer` uses `messages.parse` structured output). Both raise
  `QuizUnavailable` when `ANTHROPIC_API_KEY` is unset, which the view shows as a panel.

### `ccdashboard/folder_picker.py` — native OS folder picker
Pure stdlib (subprocess); no Textual. `pick_directories(start=None) -> list[Path]` opens
the first available of `zenity`/`kdialog`/`yad`/`qarma` (multi-select where supported),
returning the chosen dirs (or `[]` on cancel) and raising `PickerUnavailable` when none is
installed. MUST be called from a worker thread (it blocks on the dialog). Used by
`NotesConfigScreen` to let the user choose QuizMe's notes folder(s).

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
`TabbedContent` with the Config, Conversations, and QuizMe panes, and a Footer.
Bindings: `q` quit, `ctrl+r` refresh, `1`/`2`/`3` switch tabs, `/` focus the active
tab's search. On tab activation/load it calls `_ccd_active_view().focus_search()` so
focus lands in the content (every view implements `focus_search()`). On mount it kicks
off the background loader; `run(config_dir)` is the entry point used by `cc_dashboard.py`.

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
`conversations.py`, `search.py`, and `quiz.py` are pure stdlib (quiz's `anthropic`
import is lazy; `search.py` also uses `rich.text`) and each has a `__main__` offline
smoke test (`python -m ccdashboard.conversations`, `python -m ccdashboard.quiz`). The
engine modules are import-safe and headless-testable, which is how the TUI is
smoke-tested (Textual's `run_test()` pilot).

The repo now ships its first pytest suite under `tests/` (install
`requirements-dev.txt`, then `python -m pytest tests`): unit coverage of `search.py`'s
`parse_query` / `merge_ui_filters` / `rank` / `highlight` (a pure-functions engine,
so no Textual) and `conversations.py` indexing, plus one light `@integration` Pilot
test that mounts the app and asserts the table reorders and the preview updates.

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
