# CCDashboard — Architecture

A **Textual TUI** over a **UI-agnostic engine**: the engine does the work, the TUI
presents it. See `README.md` for usage; this document covers the engineering design.

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
    conversations.py       index_conversations() / search() / filter_conversations()
                           / launch_resume() over ~/.claude/projects/**/*.jsonl.
    quiz.py                load_cards() (split notes into SM-2 cards) / review() +
                           selection / gen_question() + grade_answer() (Claude).
    editor.py              open_in_editor(path) — open a config file in VS Code (CLI)
                           or the OS default; used by the Config tab's Enter action.
    tui/
      __init__.py
      app.py               CCDashboardApp (Textual App): Header, pyfiglet banner,
                           TabbedContent[Config, Conversations, QuizMe], Footer; loads
                           data in a background (@work thread) worker on mount.
      config_view.py       ConfigView — search Input + DataTable of components;
                           row-select -> editor.open_in_editor(item abs_path).
      conversations_view.py  ConversationsView — search Input + DataTable; row-select
                           -> launch_resume (clipboard + Start-menu admin launch).
      quiz_view.py         QuizView — question Static + answer TextArea + Submit;
                           gen/grade in @work workers; graceful no-key panel.
      app.tcss             Cyan/teal "Jarvis" theme.
  requirements.txt         textual / rich / pyfiglet / anthropic (pinned, pip-audit-clean).
```

---

## Data Flow

```
on_mount ──▶ @work(thread, exclusive): scan.build_view_model(config_dir)
          │                            conversations.index_conversations()
          │                            quiz.load_cards() + quiz.load_state()
          └▶ call_from_thread ──▶ ConfigView.load_items(vm)
                                  ConversationsView.load_conversations(convos)
                                  QuizView.load_quiz(cards, state)

search   ──▶ Config tab:        client-side substring filter over name/id/kind/description
         ──▶ Conversations tab: 180 ms-debounced conversations.filter_conversations(
                                index, query) — AND over a precomputed lowercased blob,
                                snippet-free (the table renders Conversation records).

Enter on a conversation row ──▶ ConversationsView._resume (@work thread)
                            ──▶ conversations.launch_resume(session_id, index)
                                (clipboard + Start-menu keystroke launch; see below)

QuizMe ──▶ load_quiz picks today's card ─▶ @work gen_question (Claude) ─▶ answer ─▶
           ctrl+s ─▶ @work grade_answer (Claude, structured) ─▶ apply_grade (SM-2)
           ─▶ save_state.
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

### `ccdashboard/conversations.py`
- `index_conversations(projects_dir=None) -> list[Conversation]` — globs
  `~/.claude/projects/*/*.jsonl`, parses each transcript into a frozen `Conversation`
  (`session_id`, `cwd`, `git_branch`, `title`, `started_at`, `last_at`,
  `message_count`, `text`, …), sorted by `last_at` desc.
  `message_count`, `text`, `search_blob`, …), sorted by `last_at` desc. `search_blob`
  is `(title + text).lower()` precomputed once, so matching never re-lowercases.
- `search(conversations, query) -> list[dict]` — AND match over `search_blob`, returns
  dicts with a snippet (used by `__main__`). `filter_conversations(conversations,
  query) -> list[Conversation]` is the snippet-free variant the TUI uses (~6.5× cheaper).
- `launch_resume(session_id, conversations, *, dry_run=False) -> dict` — validates the
  session id against `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, looks up the conversation's
  `cwd` from the index, and builds `Set-Location -LiteralPath '<cwd>'; & '<claude>'
  --resume <sid>` (claude resolved by full path so an *elevated* shell still finds it;
  cwd + path single-quote escaped). It copies that to the clipboard (`CF_UNICODETEXT`
  via ctypes) and replays Win → "powershell" → Ctrl+Shift+Enter (`keybd_event`) to open
  the user's own admin terminal — they paste it. Windows UIPI forbids typing into an
  elevated window, so delivery is via clipboard, not injection. The cwd comes from the
  transcript, never from user input.

### `ccdashboard/quiz.py`
UI-agnostic, pure stdlib except a LAZY `anthropic` import inside the two Claude calls
(so importing the module — and the TUI — never needs the SDK or network).
- `load_cards(notes_dir=None) -> list[Card]` — split every `*.md` under
  `~/Learning/Codebase` into frozen `Card`s (per `##`/`###` section, else whole file).
- SM-2 scheduling (pure): `review(state, quality, today)`, `select_today(...)`,
  `bump_streak(...)`, `apply_grade(...)` — all return NEW immutable state.
- `load_state()/save_state()` — round-trippable JSON written atomically OUTSIDE the repo
  at `~/.claude/ccdashboard/quizme.json`.
- `gen_question(card) -> str` / `grade_answer(card, q, ans) -> QuizGrade` — Claude
  (`claude-opus-4-8`; `grade_answer` uses `messages.parse` structured output). Both raise
  `QuizUnavailable` when `ANTHROPIC_API_KEY` is unset, which the view shows as a panel.

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
`conversations.py` and `quiz.py` are pure stdlib (quiz's `anthropic` import is lazy)
and each has a `__main__` offline smoke test (`python -m ccdashboard.conversations`,
`python -m ccdashboard.quiz`). The engine modules are import-safe and headless-testable,
which is how the TUI is smoke-tested (Textual's `run_test()` pilot).

---

## AppLauncher Integration

Registered in the root `apps.json` (`id: cc-dashboard`, `launchMode: console`). The
entry has a `prepare` step (`pip install -r requirements.txt`) so the launcher installs
Textual before the first run. The manifest entry is the sole integration point — no
launcher code changes.
