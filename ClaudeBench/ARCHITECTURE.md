# ClaudeBench — Architecture

Python CLI app in the MicroApps mono-repo that measures and tracks the token
footprint of the user's global Claude Code configuration (`~/.claude/`).
See `SPEC.md` for goals and rationale; this document covers the engineering design.

---

## Resolved Decisions

- **Both measurement layers** — Static (Phase 1, free, default) and Empirical
  (Phase 3, opt-in, budget-guarded). Static is the default; empirical never runs
  unless the user explicitly requests it.
- **Scope** — all of `~/.claude/`: skills, agents, MCP tool schemas, `CLAUDE.md`,
  rules, settings.json.
- **Stack** — Python 3.11+, `anthropic` SDK + stdlib; frozen dataclasses; PEP 8
  + type annotations; files 200-400 lines.
- **Output** — CLI with markdown/console tables. Textual TUI deferred.
- **Baseline model** — `claude-opus-4-8` (token counts are model-specific; configurable).
- **Empirical runs** — average N runs (default 3); skill triggered via
  `claude -p "/skill-name"` with a derived-prompt fallback.
- **Prerequisite (open item)** — `count_tokens` requires `ANTHROPIC_API_KEY` or an
  active `ant`/Claude login. If unavailable, the tokenizer falls back to
  `claude -p` baseline totals (`claude-p-fallback` tokenizer mode).

---

## Module Contract

```
ClaudeBench/
  claude_bench.py          Entry point + argparse CLI
  claudebench/
    __init__.py
    models.py              Frozen dataclasses: Component, Snapshot, Diff
    scanner.py             Walk ~/.claude -> list[Component] by kind
    tokenizer.py           count_tokens wrapper with overhead subtraction
    probe.py               Phase 3: run claude -p, parse usage JSON
    snapshot.py            Read/write timestamped JSON snapshots
    differ.py              Compare two Snapshots -> Diff
    report.py              Render markdown / console tables + diffs
  snapshots/               Git-ignored; holds all saved snapshot files
  requirements.txt
  ARCHITECTURE.md / SPEC.md / README.md
```

### `claude_bench.py`
Entry point. Parses CLI arguments (subcommands: `list`, `snapshot`, `diff`,
`bench`; global flags: `--config-dir`, `--model`, `--json`). Wires together
scanner -> tokenizer -> snapshot -> differ -> report in the appropriate order.
Returns exit code 0 on success, non-zero on error.

### `claudebench/models.py`
Frozen dataclasses only — no logic. Defines:
- `Component` — one config item (kind, id, name, path, content_hash,
  tokens_always_loaded, tokens_invocation, empirical).
- `Snapshot` — top-level record (taken_at, label, config_dir, model,
  tokenizer, totals, components).
- `Diff` — result of comparing two snapshots (added, removed, changed,
  token deltas per component and in aggregate).

All mutations return new copies; nothing is mutated in-place.

### `claudebench/scanner.py`
Input: config directory path (default `~/.claude/`).
Output: `list[Component]` with kind, id, name, and path populated; token
fields left at zero (filled in by tokenizer).

Walk rules:
- `skills/` -> kind `skill`; id = filename stem.
- `.claude/agents/` -> kind `agent`; id = filename stem.
- MCP server tool-schema files -> kind `mcp`; id = server slug.
- `CLAUDE.md` + `rules/**` -> kind `memory` / `rule`.
- `settings.json` -> kind `setting`.

Produces a stable, sorted list so snapshots are deterministic.

### `claudebench/tokenizer.py`
Input: `Component`, model string.
Output: `Component` with `tokens_always_loaded` and `tokens_invocation` set.

Calls `anthropic.Anthropic().messages.count_tokens()` twice per component
(once for the always-loaded portion, once for the invocation body). Subtracts a
fixed **per-call message-wrapper overhead** (system prompt envelope, tool-list
frame) from each raw count so per-component numbers reflect only that
component's content, not the API call scaffolding. The overhead constant is
measured once at startup using an empty content probe and stored for the session.

If `count_tokens` is unavailable (no API credential), falls back to a
`claude -p` baseline probe via `probe.py` and records `tokenizer:
"claude-p-fallback"`. In fallback mode only totals are available; per-component
breakdown is approximated by relative file size.

### `claudebench/probe.py`
Used by Phase 3 (`bench` command) and by the tokenizer fallback.

Phase 3 path: for each target component, runs
`claude -p "/skill-name" --output-format json` (or a derived prompt when no
skill name applies). Parses `usage.input_tokens` and `usage.output_tokens` from
the JSON response. Averages across N runs (default 3). Records min/max alongside
mean. Returns an `empirical` block that is attached to the `Component`.

Budget guard: before each `claude -p` invocation, checks remaining budget
against a user-supplied `--budget` ceiling. Aborts with a clear message if the
next run would exceed it.

### `claudebench/snapshot.py`
Input: `Snapshot` dataclass.
Output: JSON file written to `snapshots/<ISO8601-timestamp>[_<label>].json`.

Also exposes `load(path)` and `find_latest(n)` for the differ and CLI.
File format is validated against `snapshot.schema.json` on both write and read.

### `claudebench/differ.py`
Input: two `Snapshot` objects (from_snap, to_snap).
Output: `Diff` dataclass — added components, removed components, changed
components with per-field deltas (tokens_always_loaded delta,
tokens_invocation delta), and aggregate totals delta by kind.

Components are matched by `id` + `kind`. A `content_hash` change with no token
change is recorded as "modified (no cost change)".

### `claudebench/report.py`
Input: `Snapshot` or `Diff`; output format flag (`--json` or console/markdown).
Output: formatted string written to stdout.

Console mode renders a table (component name | kind | always-loaded tokens |
invocation tokens | empirical mean input | empirical mean output).
Diff mode highlights added/removed rows and shows +/- deltas.
`--json` mode emits the raw `Snapshot` or `Diff` as JSON.

---

## Data Flow

```
~/.claude/
    |
    v
scanner.py          -> list[Component]  (paths + kind; tokens = 0)
    |
    v
tokenizer.py        -> list[Component]  (tokens_always_loaded + tokens_invocation filled)
    |
    v
snapshot.py  write  -> snapshots/<timestamp>.json
    |
    v
report.py           -> console/markdown table

                         [EMPIRICAL PATH — opt-in, --bench flag only]
                         |
                    probe.py  (runs claude -p N times per component)
                         |
                    Component.empirical filled
                         |
                    snapshot.py  write  (empirical block included in JSON)
                         |
                    report.py  (extended table with input/output means)

diff command:
  snapshot.py load (from) + snapshot.py load (to)
    |
    v
  differ.py -> Diff
    |
    v
  report.py -> diff table
```

---

## `tokens_always_loaded` vs `tokens_invocation` per Kind

| Kind | `tokens_always_loaded` | `tokens_invocation` |
|---|---|---|
| `skill` | Frontmatter only (`name` + `description` block) | Full `.md` body |
| `agent` | Full agent system-prompt file (always in context) | `null` |
| `mcp` | Tool-schema JSON for that server (always registered) | `null` |
| `memory` | Full `CLAUDE.md` or rules file | `null` |
| `rule` | Full rules file content | `null` |
| `setting` | Serialized settings.json content | `null` |

For kinds where only `tokens_always_loaded` applies, `tokens_invocation` is
stored as `null` in the snapshot and reported as `—` in tables.

---

## Snapshot Schema

The canonical JSON structure and field constraints live in `snapshot.schema.json`
(JSON Schema draft-07). The authoritative top-level fields are:

```
taken_at        ISO 8601 string
label           string | null
config_dir      string
model           string  (e.g. "claude-opus-4-8")
tokenizer       "count_tokens" | "claude-p-fallback"
totals          { always_loaded, invocation, by_kind: { skill, agent, mcp, memory, rule, setting } }
components[]    { kind, id, name, path, content_hash ("sha256:..."),
                  tokens_always_loaded, tokens_invocation,
                  empirical: null | { runs, input_mean, output_mean,
                                      input_min, input_max, output_min, output_max,
                                      budget_spent } }
```

Do not duplicate the schema here; `snapshot.schema.json` is the single source of
truth and is used for runtime validation.

---

## Free vs Allowance Boundary

| Layer | Command | Cost | Requires |
|---|---|---|---|
| Static (Phase 1-2) | `list`, `snapshot`, `diff` | Free — `count_tokens` is not billed | API credential (or fallback mode) |
| Empirical (Phase 3) | `bench` | Spends the 4-hour token allowance | `--yes` confirmation; optional `--budget` cap |

The `bench` command always prints an estimate of budget spend and requires either
`--yes` or an interactive confirmation before issuing any `claude -p` invocations.

---

## AppLauncher Integration (Phase 4)

Register ClaudeBench as a 4th app in the repo's root `apps.json` so it appears
in AppLauncher alongside MeetingTracker, MeetingNotesOverlay, and ClaudePanes.
No personal data is bundled — snapshots stay in the git-ignored `snapshots/` dir.

Entry shape (matching the existing `apps.json` schema):

```json
{
  "id": "claude-bench",
  "name": "ClaudeBench",
  "description": "Measure and track the token footprint of your ~/.claude/ config",
  "type": "python",
  "mode": "console",
  "path": "ClaudeBench/claude_bench.py",
  "args": []
}
```

A Textual TUI wrapper is deferred; the `claude_bench.py` entry point will
accept a future `--tui` flag without breaking the existing CLI surface.
