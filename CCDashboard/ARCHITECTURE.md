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
    conversations.py       index_conversations() / search() / launch_resume()
                           over ~/.claude/projects/**/*.jsonl. Has a __main__ dry-run.
    tui/
      __init__.py
      app.py               CCDashboardApp (Textual App): Header, pyfiglet banner,
                           TabbedContent[Config, Conversations], Footer; loads data
                           in a background (@work thread) worker on mount.
      config_view.py       ConfigView — search Input + DataTable of components.
      conversations_view.py  ConversationsView — search Input + DataTable; row-select
                           -> launch_resume (elevated PowerShell).
      app.tcss             Cyan/teal "Jarvis" theme.
  requirements.txt         textual / rich / pyfiglet (pinned, pip-audit-clean).
```

---

## Data Flow

```
on_mount ──▶ @work(thread, exclusive): scan.build_view_model(config_dir)
          │                            conversations.index_conversations()
          └▶ call_from_thread ──▶ ConfigView.load_items(vm)
                                  ConversationsView.load_conversations(convos)
                              ──▶ populate the two DataTables

search   ──▶ Config tab:        client-side substring filter over name/id/kind/description
         ──▶ Conversations tab: conversations.search(index, query)  (AND across title+text)

Enter on a conversation row ──▶ ConversationsView._resume (@work thread)
                            ──▶ conversations.launch_resume(session_id, index)
```

Indexing 100+ transcripts runs off the UI thread; results are pushed back with
`call_from_thread`. Refresh (`ctrl+r`) re-runs the same worker.

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
- `search(conversations, query) -> list[dict]` — AND match across title + full text,
  returns dicts with a snippet.
- `launch_resume(session_id, conversations, *, dry_run=False) -> dict` — validates the
  session id against `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`, looks up the conversation's
  `cwd` from the index, writes a `.ps1` (`Set-Location -LiteralPath '<cwd>';
  claude --resume <sid>`), and `Start-Process -Verb RunAs` elevates a PowerShell to
  run it. The cwd comes from the transcript, never from user input; single quotes are
  escaped.

### `ccdashboard/tui/app.py` — `CCDashboardApp(App)` / `run(config_dir)`
`CSS_PATH = "app.tcss"`. Composes Header (clock), a `pyfiglet` banner Static, a
`TabbedContent` with the Config and Conversations panes, and a Footer. Bindings: `q`
quit, `ctrl+r` refresh, `1`/`2` switch tabs. On mount it kicks off the background
loader; `run(config_dir)` is the entry point used by `cc_dashboard.py`.

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
`conversations.py` is pure stdlib and has a `__main__` dry-run smoke test
(`python -m ccdashboard.conversations`). Both engine modules are import-safe and
headless-testable, which is how the TUI is smoke-tested (Textual's `run_test()` pilot).

---

## AppLauncher Integration

Registered in the root `apps.json` (`id: cc-dashboard`, `launchMode: console`). The
entry has a `prepare` step (`pip install -r requirements.txt`) so the launcher installs
Textual before the first run. The manifest entry is the sole integration point — no
launcher code changes.
