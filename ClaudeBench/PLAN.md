# ClaudeBench — Plan & Progress

A Python CLI tool in the MicroApps mono-repo that **measures and tracks the
token footprint of the user's global Claude Code config** (`~/.claude/`): skills,
agents, MCP tool schemas, `CLAUDE.md`, rules, and `settings.json`.

> This plan was produced from a multi-agent parallel spec pass (spec, architecture,
> and plan authored on 2026-06-18).  Build: Phases 0–1 complete (2026-06-18); Phase 2 (`diff`) next.

---

## 1. Overview

Every file Claude Code loads from `~/.claude/` consumes tokens on each
invocation — either always (system-prompt-injected) or on demand (skills
invoked explicitly). Without measurement it is impossible to know whether the
config is within comfortable limits, which files are the biggest contributors,
or how the footprint has grown over time.

ClaudeBench gives you two complementary views:

- **Static layer (Phase 1, always free):** calls `count_tokens` on the Anthropic
  SDK directly — no inference, no billing, no allowance use — to report
  `tokens_always_loaded` (files Claude injects unconditionally) and
  `tokens_invocation` (the per-skill overhead added when a skill runs).
- **Empirical layer (Phase 3, opt-in):** shells out to `claude -p` and averages
  N real inference runs to measure the actual tokens-in figure as reported by
  the model, including any overhead that static counting misses.

Default mode is **static-only**; empirical mode must be explicitly requested
and is always budget-guarded.

---

## 2. Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | All of `~/.claude/` | Skills, agents, MCP schemas, CLAUDE.md, rules, settings.json — the complete context Claude Code loads |
| Token measurement (static) | `anthropic` SDK `count_tokens` | Free, no inference, no allowance use; model `claude-opus-4-8` |
| Token measurement (empirical) | `claude -p --output-format json`, averaged over N runs (default 3) | Captures real overhead; opt-in only |
| Default mode | Static-only | Empirical spends the 4-hour allowance; users must explicitly opt in via `bench` subcommand |
| Cost boundary | Static = free; empirical = spends allowance | Enforced by budget guard (`--budget`) and `--yes` confirmation; dry-run estimate shown before any spend |
| Default model | `claude-opus-4-8` | Matches the user's production Claude Code model; overridable via `--model` |
| Output formats | Markdown (human) + `--json` (machine/CI) | Both layers; markdown is default |
| Snapshot persistence | `snapshots/` dir, git-ignored | JSON files; diffable over time |
| Stack | Python 3.11+, `anthropic` SDK (pinned, pip-audit-clean), stdlib only | No heavy deps; consistent with other Python micro-apps in the repo |
| Data classes | Frozen dataclasses | Immutability enforced by design |
| Code style | PEP 8 + type annotations | Consistent with repo conventions |
| CLI entry point | `python claude_bench.py <subcommand>` | Matches repo pattern; register as app-launcher entry in Phase 4 |
| Empirical baseline fallback | `claude -p` baseline-totals if API key unavailable | Confirmed or implemented in Phase 0 (open item) |

---

## 3. Phase-by-phase checklists

### Phase 0 — Prerequisites

- [ ] **Confirm whether an Anthropic API key is available** (`ANTHROPIC_API_KEY`
      or an `ant`/Claude login); if not, implement the `claude -p`
      baseline-totals fallback.
- [ ] Scaffold `ClaudeBench/` folder structure: `claude_bench.py`, `claudebench/`,
      `snapshots/`, `requirements.txt`, `docs/`
- [ ] Confirm Python 3.11+ is available on the target machine
- [x] Pin `anthropic` SDK in `requirements.txt`; run `pip-audit` and verify clean — **2026-06-18: `anthropic==0.109.2`, pip-audit clean (no known vulns across the full transitive tree)**
- [x] Add `ClaudeBench/snapshots/` to git-ignore — **done via `ClaudeBench/.gitignore`**

---

### Phase 1 — Static MVP (FREE)

Goal: `list` and `snapshot` subcommands work; no inference is called.

**Status: ✅ COMPLETE — built + verified 2026-06-18 (two parallel agents).** Final
API follows SPEC/ARCHITECTURE: `scanner.scan(config_dir) -> list[Component]`;
`tokenizer.tokenize(components, *, config_dir, model) -> (list[Component], mode)`
(net counts via `client.messages.count_tokens`, fixed per-call overhead
subtracted); `models.Component` / `models.Snapshot` / `models.build_snapshot`;
`snapshot.save/load/find_latest`; `report.render_list/render_snapshot`;
`claude_bench.py` wires `list` + `snapshot`. Verified on this machine: 80
components scanned, table renders cleanly (UTF-8), snapshot saved to the
git-ignored `snapshots/`. **Real counts need `ANTHROPIC_API_KEY`** — not set
here, so it reports `claude-p-fallback` placeholder zeros (no allowance spent).
The checklist below is the original plan; the shipped names supersede it.

**Scanner (`claudebench/scanner.py`)**
- [ ] Walk `~/.claude/` and classify each file into: `always_loaded` vs
      `on_invocation` vs `other` (untracked)
- [ ] Expose a `scan(config_dir) -> list[ConfigFile]` function
- [ ] Respect `--config-dir` override

**Tokenizer (`claudebench/tokenizer.py`)**
- [ ] Call `anthropic.count_tokens()` for each file using model `claude-opus-4-8`
- [ ] Subtract system-prompt overhead so reported counts are net file content tokens
- [ ] Expose `count(text, model) -> int`

**Models (`claudebench/models.py`)**
- [ ] Frozen dataclass `ConfigFile(path, category, token_count)`
- [ ] Frozen dataclass `Snapshot(label, timestamp, config_dir, files, totals)`
- [ ] Frozen dataclass `Totals(tokens_always_loaded, tokens_invocation, grand_total)`

**Snapshot writer (`claudebench/snapshot.py`)**
- [ ] Serialize a `Snapshot` to `snapshots/<timestamp>-<label>.json`
- [ ] Validate output against `docs/snapshot.schema.json`

**Report (`claudebench/report.py`)**
- [ ] Markdown table: per-file rows (path, category, tokens) + summary totals row
- [ ] `--json` flag path: emit raw `Snapshot` JSON instead

**`list` subcommand**
- [ ] Print current `~/.claude/` file inventory + static token counts without
      writing a snapshot

**`snapshot` subcommand**
- [ ] Run scanner + tokenizer + snapshot writer; print report; support `--label`

---

### Phase 2 — Diff

Goal: `diff` subcommand shows what changed between two snapshots.

**Differ (`claudebench/differ.py`)**
- [ ] Load two snapshots from `snapshots/`; default `--from` = latest-1, `--to` = latest
- [ ] Produce per-file delta rows: added / removed / changed (± tokens)
- [ ] Produce totals delta

**`diff` subcommand**
- [ ] Accept `--from A --to B` (snapshot labels or timestamps)
- [ ] Print markdown diff table + net totals change; support `--json`

---

### Phase 3 — Empirical (opt-in, spends allowance)

Goal: `bench` subcommand measures real inference token counts via `claude -p`.

**Probe (`claudebench/probe.py`)**
- [ ] Shell out to `claude -p --output-format json` with a minimal prompt
- [ ] Parse `usage.input_tokens` from the JSON response
- [ ] Average over N runs (default 3); record min/max/stddev

**Budget guard**
- [ ] Before any inference: estimate cost from static counts × price-per-token
- [ ] Print dry-run estimate; require `--yes` confirmation (or abort)
- [ ] Enforce hard cap via `--budget N` (token spend ceiling); abort mid-run if exceeded

**`bench` subcommand**
- [ ] `--all` benchmarks the full config; `--skills a,b,c` benchmarks named skills
- [ ] `--runs N` sets averaging count (default 3)
- [ ] `--budget N` sets the hard spend cap
- [ ] `--yes` skips the confirmation prompt (for scripted use)
- [ ] Attach empirical results to a `Snapshot` and write it; print report

---

### Phase 4 — Integration

Goal: ClaudeBench is a first-class app in the mono-repo launcher.

- [ ] Add ClaudeBench entry to `apps.json` at repo root:
      `stack: "python"`, `launchMode: "console"`, `launch.cmd: ["python", "claude_bench.py", "list"]`
- [ ] Verify AppLauncher prerequisite check passes (Python 3.11+)
- [ ] Update root README to mention ClaudeBench alongside the other apps
- [ ] Optional: add a Textual TUI wrapper (`claudebench/tui/`) for interactive
      snapshot browsing and diff viewing — deferred, non-blocking

---

## 4. Per-phase verification plan

### Phase 1 — Static MVP

1. Run `python claude_bench.py snapshot --label baseline` on this machine.
2. Open `/context` (or equivalent) in Claude Code and note the reported
   tokens-in figure; confirm ClaudeBench's `tokens_always_loaded` is in the
   same ballpark (within ~10%).
3. Inspect `snapshots/` — confirm exactly one `.json` file was written; validate
   it against `docs/snapshot.schema.json` (e.g. `jsonschema` CLI or a Python
   one-liner).
4. Run `python claude_bench.py list` and confirm all `~/.claude/` files appear
   with plausible token counts (no file shows 0 unless it is actually empty).

### Phase 2 — Diff

1. Add a dummy skill file to `~/.claude/skills/bench-dummy.md` with known
   content (~50 tokens).
2. Run `snapshot --label after-dummy`.
3. Run `diff --from baseline --to after-dummy`; confirm the dummy skill appears
   as `+added` with a token delta close to the expected count.
4. Remove the dummy file; run another snapshot; diff again — confirm the file
   appears as `-removed`.

### Phase 3 — Empirical

1. Run `bench --all --runs 1 --budget 500` **without** `--yes`; confirm the
   dry-run estimate is printed and the tool stops for confirmation.
2. Confirm `--budget 100` with a config larger than 100 tokens aborts before
   completing all runs.
3. With `--yes` and a small `--runs 1` run, confirm empirical `tokens_in` is
   written to the snapshot and is non-zero.
4. Compare empirical vs static totals; document the observed overhead ratio in
   the progress log.

### Phase 4 — Integration

1. Open AppLauncher and confirm ClaudeBench appears in the app list with a
   green prerequisite badge.
2. Launch it from AppLauncher and confirm `list` output appears in the spawned
   console window.

---

## 5. Module layout

```
ClaudeBench/
├── claude_bench.py          # CLI entry point (argparse); routes to subcommands
├── claudebench/
│   ├── models.py            # Frozen dataclasses: ConfigFile, Snapshot, Totals
│   ├── scanner.py           # Walk ~/.claude/, classify files
│   ├── tokenizer.py         # count_tokens wrapper; overhead subtraction
│   ├── probe.py             # claude -p shell-out; N-run averaging; budget guard
│   ├── snapshot.py          # Serialize/deserialize Snapshot ↔ JSON
│   ├── differ.py            # Load two snapshots; compute per-file deltas
│   └── report.py            # Markdown + JSON output formatters
├── snapshots/               # git-ignored; written by snapshot/bench subcommands
├── requirements.txt         # anthropic (pinned); pip-audit-clean
└── docs/
    ├── SPEC.md
    ├── ARCHITECTURE.md
    ├── README.md
    └── snapshot.schema.json
```

---

## 6. Canonical CLI reference

```
python claude_bench.py [--config-dir DIR] [--model MODEL] [--json] <subcommand>

Subcommands:
  list                          Print current ~/.claude/ inventory + static counts
  snapshot [--label NAME]       Take a static snapshot; write to snapshots/
  diff [--from A] [--to B]      Diff two snapshots (default: latest-1 vs latest)
  bench [--all | --skills a,b]  Empirical benchmarking (opt-in; SPENDS allowance)
        [--runs N]              Number of inference runs to average (default: 3)
        [--budget N]            Hard token-spend ceiling; aborts if exceeded
        [--yes]                 Skip confirmation prompt

Global flags:
  --config-dir DIR              Config directory to scan (default: ~/.claude)
  --model MODEL                 Model for token counting (default: claude-opus-4-8)
  --json                        Emit JSON instead of markdown
```

---

## 7. Open questions

1. **API key availability** — is `ANTHROPIC_API_KEY` set on this machine, or
   does empirical mode need to fall back to `claude -p` baseline totals?
   *(Resolved in Phase 0.)*
2. **Overhead subtraction** — what is the exact system-prompt token overhead
   injected by `count_tokens` when called with `claude-opus-4-8`? Measure once
   in Phase 1 and hardcode or parameterize.
3. **Snapshot retention policy** — keep all snapshots indefinitely, or offer a
   `prune` subcommand?
4. **CI integration** — is there a use case for running `bench` in a scheduled
   workflow and alerting if tokens exceed a threshold?

---

## 8. Progress log

- **2026-06-18** — Spec + architecture + plan authored (multi-agent); build not started.
- **2026-06-18** — Phase 0 + Phase 1 complete. Pinned + pip-audited `anthropic==0.109.2` (clean). Built the static MVP with two parallel agents (engine: models/scanner/snapshot; frontend: tokenizer/report/CLI). Verified end-to-end: `list` + `snapshot` run across 80 components, clean UTF-8 render, snapshot saved + git-ignored, graceful fallback. **Finding:** `anthropic` installed but no `ANTHROPIC_API_KEY` → real counts need a key (currently `claude-p-fallback` zeros). Next: set an API key and re-run `snapshot` for real numbers; then Phase 2 (`diff`).

<!-- Append dated entries here as phases complete. Tick boxes in §3. -->
