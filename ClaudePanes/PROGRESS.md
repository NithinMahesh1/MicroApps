# ClaudePanes Progress

## Status

**Current phase:** Phase 1 COMPLETE — code + 89 tests + CI + 2 commits on `main` (`3ab2599` MVP, `434806e` hardening). v0.1.0-ready, pending one human-launch check.
**Last updated:** 2026-05-27
**Next milestone:** ⚠️ Confirm a real terminal launch works (blocking gate below), then tag `v0.1.0`.

## Next Up (start here when resuming)

> ⚠️ **BLOCKING GATE — verify it actually works before ANY new work.**
> Everything so far is verified by unit tests (89/89) and `--dry-run` output **only**. No human has watched ClaudePanes drive a real terminal end-to-end yet. Do NOT start a new feature, refactor, or the v0.1.0 tag until this passes.

- [ ] **Launch for real:** run `python claude_panes.py start examples/solo-claude.toml` and confirm Windows Terminal opens and the pane's command actually runs.
- [ ] **Multi-pane:** run `python claude_panes.py start examples/ide-layout.toml` and confirm the splits/sizes look right.
- [ ] If a pane misbehaves, diff against `--dry-run` output and check `docs/troubleshooting.md`.
- [ ] Mark this gate done here once a real launch is confirmed working.

Full run/install walkthrough + status lives in **`instructions.md`** (repo root).

### After the gate passes
1. Tag `v0.1.0` (`git tag v0.1.0 && git push --tags`) — needs the repo pushed to GitHub; triggers `release.yml`.
2. Deferred gaps (non-blocking): Zellij `working_dir`/`$SHELL`, `--dry-run` for absent terminals, a `shell_prelude` example. (See Phase 1.6 "Remaining known gaps".)

### Code-fix audit (2026-05-22, post-compact)
Verified via grep + full test run that the 5 "pending" bugs were already fixed on disk; the staleness was in this doc, not the code:
- `_tokenize` not present (removed); all 4 adapters pass `cmd` as a single opaque argv element wrapped via `_shell_wrap` / `cmd.exe /c`. One residual gap closed today: `WindowsTerminalAdapter.build_command` now prepends `cmd.exe /c` for both first-pane and split-pane branches.
- `_warn_unknown_keys` helper exists; called at top-level, pane, tab, and shell scopes; `test_unknown_field_handling` passes.
- `TmuxAdapter` uses `session = f"{layout.name}-{time.time_ns() // 1_000_000}"`.
- `_kdl_pane_line` emits `size "30%"` (quoted percent string).
- `ZellijAdapter.execute` uses `tempfile.TemporaryDirectory(prefix="claudepanes-")` context manager.
- Full suite: 38 tests, 0 failures, 0 errors.

## Resume this conversation

Each session's handoff lives under the local Claude Code session folder (`ClaudeChats/sessions/<date>_claudepanes_*/`); `summary.md` there captures the full state.

## Roadmap

### Phase 0 — Documentation (complete)
- [x] README.md
- [x] docs/architecture.md
- [x] docs/design-decisions.md
- [x] docs/security.md
- [x] docs/terminal-adapters.md
- [x] docs/config-format.md
- [x] docs/cli-spec.md
- [x] docs/usage-examples.md
- [x] docs/permission-allowlist.md
- [x] docs/development-guide.md
- [x] docs/related-claude-features.md
- [x] PROGRESS.md (this file)
- [x] .gitignore
- [x] Initial git commit (`dc29978` — docs: initial documentation set)

### Phase 1 — MVP code (written; verification pending)
- [x] Single-file Python tool: `claude_panes.py`
  - [x] CLI: argparse subcommands `start`, `list`, `validate`, `detect`, `version`
  - [x] Config loader: TOML parsing via stdlib `tomllib`, schema validation
  - [x] Layout dataclasses (Pane, Tab, Layout — frozen)
  - [x] Terminal detector: `shutil.which` priority lookup
  - [x] WindowsTerminalAdapter (`wt.exe`)
  - [x] WezTermAdapter (multi-step pane-id threading)
  - [x] TmuxAdapter
  - [x] ZellijAdapter (KDL layout file emission)
  - [x] `--dry-run` mode
- [x] Test fixtures (10 files under `tests/fixtures/`)
- [x] `tests/test_config.py`
- [x] `tests/test_adapters.py`
- [x] Example layouts (6 files under `examples/`)
- [x] CI workflow (`.github/workflows/ci.yml`) — pulled forward from Phase 3
- [x] Install scripts (`install.ps1`, `install.sh`) — pulled forward from Phase 4
- [x] `LICENSE` (MIT)
- [x] `CHANGELOG.md`
- [x] Run `python -m unittest discover tests` end-to-end to verify spec/code alignment
  - 38 tests, all green as of 2026-05-22.
- [x] Smoke-test against `examples/solo-claude.toml` with `--dry-run` — confirmed green 2026-05-13
- [x] `README.md` Quick Start updated with confirmed install/run commands
- [x] **5 `claude_panes.py` bug fixes** — verified done 2026-05-22 (see audit note in Status above)
- [ ] Second git commit (`feat: initial MVP code, tests, CI, install scripts, license`)

### Phase 1.5 — Scope additions landed 2026-05-22 (not in original roadmap)
- [x] `SECURITY.md` (top-level)
- [x] `CONTRIBUTING.md` (top-level)
- [x] `docs/installation.md`
- [x] `docs/troubleshooting.md`
- [x] `docs/faq.md`
- [x] `docs/migration-guide.md` (v0.1.0 baseline only)
- [x] `docs/code-walkthrough.md`
- [x] `.github/ISSUE_TEMPLATE/bug_report.md`
- [x] `.github/ISSUE_TEMPLATE/feature_request.md`
- [x] `.github/pull_request_template.md`
- [x] `examples/with-env-vars.toml` (env-var expansion in `working_dir`)
- [x] `examples/parent-pane-tree.toml` (4-pane non-linear split tree)

### Phase 1.6 — Audit findings (RESOLVED 2026-05-22 via 5-agent fan-out)
- [x] CI hardening: added `permissions: contents: read` + `concurrency` (cancel-in-progress) to `ci.yml`; added `release.yml` (tag-gated, test-gated, publishes `claude_panes.py` + `.sha256`).
- [x] Cross-platform: `_shell_wrap` now honors `$SHELL` (`-lc`) with a `/bin/sh -c` fallback; `_apply_prelude` joins prelude + cmd with ` && `. wt `;` argv-quoting smoke-tested via `--dry-run` (correct).
- [x] Test coverage: added `test_main`, `test_detect`, `test_adapter_flags`, `test_validation`, `test_prelude_and_shell`, `test_kdl_escape` — suite now **89 tests** (was 38).
- [x] Security pass: `bandit` + manual review — no exploitable findings. Hardened `_kdl_escape` to also escape `\n`/`\r`/`\t` (LOW, defense-in-depth).

#### Remaining known gaps (deferred — not blocking v0.1.0)
- Zellij silently drops a pane's `working_dir` (no `cwd` in KDL); pinned by `test_working_dir_not_emitted_today` so a future fix is a deliberate flip.
- Zellij `_kdl_pane_line` hardcodes `bash` for the POSIX command head (doesn't honor `$SHELL` like `_shell_wrap`).
- `start --dry-run --terminal NAME` requires NAME installed; can't preview an absent terminal's command.
- No `examples/` layout demonstrates `shell_prelude`.
- Installer one-liners (once the repo is public) should document a download-then-verify-`.sha256` flow.

### Phase 2 — Cross-terminal support (rolled into Phase 1)
- [x] WezTerm adapter (`wezterm cli`)
- [x] tmux adapter
- [x] Zellij adapter (KDL layout file emission)
- [x] Adapter priority override via TOML and CLI flag
- [x] Detect command + JSON output

### Phase 3 — Quality (not started)
- [ ] Tests: stdlib `unittest`, no third-party test runner
- [ ] Config validation error messages with line numbers
- [ ] Logging via stdlib `logging` to stderr
- [ ] Lint with `ruff` (optional dev dep, NOT runtime dep)
- [ ] CI: GitHub Actions matrix (Windows + Ubuntu, Python 3.11 + 3.12 + 3.13)

### Phase 4 — Polish (not started)
- [ ] `claude-panes new <name>` scaffolding command
- [ ] `claude-panes list --json` output
- [ ] Per-pane env overrides (in TOML)
- [ ] Better error messages when host terminal launch fails
- [ ] Distribution: pipx-installable, single-file script also works standalone

### Out of scope (explicitly deferred — see design-decisions.md)
- [ ] PTY hosting / terminal emulation
- [ ] TUI dashboard
- [ ] GUI
- [ ] Daemon / long-running orchestrator
- [ ] Input broadcasting across panes
- [ ] Running-state observation
- [ ] Sandbox enforcement (delegated to Claude Code's /sandbox in WSL)

## Open questions

(none)

## Decisions log

A short, dated log of meaningful decisions. One line each. Cross-reference design-decisions.md for the full ADRs.

- 2026-05-13: Project kicked off. Scope: Python launcher, not a terminal emulator. Zero third-party deps. Initial doc set being written by parallel agents. (See ADR-001 through ADR-010 in design-decisions.md.)
- 2026-05-20: Q1 resolved → `start` is fire-and-forget. See ADR-011.
- 2026-05-20: Q2 resolved → keep `cmd.exe /c wt.exe` wrapper, no user knob. See ADR-012.
- 2026-05-20: Q3 resolved → TOML-level `terminal` override only; per-user config.toml deferred to Phase 4.
- 2026-05-20: Q4 resolved → MVP `validate` fails fast on first error; cli-spec §2.3 updated to match. Multi-error aggregation deferred to Phase 3.
- 2026-05-20: Q5 resolved → on Windows, users invoke ClaudePanes from inside WSL when using tmux. See ADR-013.

## Progress log

Append-only chronological log. Newest at the bottom. One bullet per meaningful event. Date each entry.

- 2026-05-13: Repo created and git initialized. .gitignore added (standard Python).
- 2026-05-13: Documentation phase started: 10 parallel agents dispatched to write README + 8 doc files + this PROGRESS.md + a development guide.
- 2026-05-13: Documentation phase complete. Note: the `architect` and `claude-code-guide` agents lacked the Write tool in their toolsets, so `docs/architecture.md` and `docs/permission-allowlist.md` were written directly rather than by the agents. All 11 docs now exist on disk.
- 2026-05-13: Going forward, consolidated to single-agent (or direct) execution rather than parallel multi-agent. Phase 1 (code) paused pending user go-ahead.
- 2026-05-13: Initial documentation commit landed as `dc29978` on `main`. 12 files, 3434 insertions.
- 2026-05-13: Researched Anthropic's recent `claude agents` / `--bg` background-session feature. Verdict: complementary to ClaudePanes (background task running vs. visual pane layout). Added `docs/related-claude-features.md` capturing the relationship and Dakota's quote.
- 2026-05-13: Phase 1 dispatched: 8 parallel agents for `claude_panes.py`, test fixtures, config tests, adapter tests, example layouts, CI workflow, install scripts, and LICENSE/CHANGELOG.
- 2026-05-13: Phase 1 dispatch returned all artifacts. `claude_panes.py` was written despite the initial agent-rejection notice (file is on disk and complete). Test fixtures (10 files), test files (2 modules), examples (6 files), CI workflow, install scripts (PowerShell + bash), LICENSE, and CHANGELOG all present. Pending: end-to-end test run, smoke test, and second commit.
- 2026-05-13: Session wrapping for context handoff. PROGRESS Next Up section now leads with HANDOFF.md / `/compact` as the first action on resume.
- 2026-05-14: Resume session. 8-agent sweep ran tests/smoke/code-review/spec-audit/adapter-audit/README-update/CHANGELOG/open-questions. Findings: 38 tests with 5 fails + 1 error (mostly test-side bugs); `examples/native-windows.toml:10` invalid TOML literal; code review surfaced CRITICAL `_tokenize` defect + ~11 HIGH items; doc auditor flagged 15+ drift items.
- 2026-05-20: 5-agent sweep landed test-side fixes (`test_adapters.py` x4, `test_config.py` x1), native-windows.toml fix, decisions log + ADRs 011/012/013, doc drift fixes (`docs/config-format.md` + `docs/terminal-adapters.md`). **Note:** the parallel `claude_panes.py` code agent was NEVER actually dispatched (the previous PROGRESS entry was incorrect — only 4 of 5 planned agents ran).
- 2026-05-22: 13 of 15 agents landed scope additions (SECURITY.md, CONTRIBUTING.md, docs/installation.md, docs/troubleshooting.md, docs/faq.md, docs/migration-guide.md, docs/code-walkthrough.md, 3 .github templates, 2 new examples). 3 read-only audits (CI, cross-platform, test coverage) returned findings. User rejected the `claude_panes.py` code-fix agent on multiple attempts; deferred those edits to a tighter-loop session.
- 2026-05-22 (post-compact): Audit pass on the 5 "pending" code bugs found 4 of 5 already landed on disk (config warning, tmux ms-suffix, Zellij size unit, Zellij TemporaryDirectory). Single remaining gap — `WindowsTerminalAdapter` not wrapping `pane.cmd` with `cmd.exe /c` — closed via one direct edit. Full suite green: 38/38. Next action is the second git commit.
- 2026-05-22: **Second commit landed as `3ab2599`** on `main` — `feat: initial MVP` (43 files, 3939 insertions: code, tests, examples, CI, installers, LICENSE, docs). Pre-commit security sanity check passed (no secrets, argv-list subprocess, no `shell=True`).
- 2026-05-22: 5-agent fan-out on deferred Phase 1.6 + security. Results: CI hardened + `release.yml` added; `_shell_wrap` now honors `$SHELL`/`/bin/sh`; `_apply_prelude` joins with ` && `; +51 tests (89 total). Security pass (`bandit` + manual) found no exploitable vulns; hardened `_kdl_escape` for control chars. Fixed `with_shell_prelude.toml` trailing-`&&` quirk. Smoke-tested wt/env-var dry-runs (CRITICAL `_tokenize` fix verified: `wsl -- bash -lc '... && claude'` preserved intact). CHANGELOG corrected (removed false `_tokenize`/`mkdtemp` claims). **Landed as `434806e`** (23 files, +987).

## How to update this file

- Tick off checkboxes when items complete.
- Add a dated bullet to the Progress log every meaningful step (commits, builds, decisions, demos).
- Move open questions to Decisions log when resolved.
- Don't rewrite history — append.

## Quick visual status

A small ASCII status board for the impatient:

```
Docs:   [##########] complete; synced to code (prelude/shell-wrap/security)
MVP:    [##########] code green; cross-platform + security hardening applied
Tests:  [##########] 89/89 passing
CI:     [##########] hardened (permissions + concurrency) + release.yml added
Commit: [######## ] dc29978 docs + 3ab2599 MVP on main; Phase 1.6 follow-up pending
Sec:    [##########] bandit + manual audit — no exploitable findings
Polish: [######### ] Phase 1.6 resolved; minor Zellij/dry-run gaps deferred
```

(Update the bars as phases complete. ##### = 10%, full bar = 100%.)
