# ClaudeBench — Functional Specification

## Overview & Goal

ClaudeBench is a Python CLI app in the MicroApps mono-repo that measures and tracks
the **token footprint** of the user's global Claude Code configuration (`~/.claude/`).
It is a normal standalone app (not a Claude Code skill) that shells out to the `claude`
CLI only for empirical measurements.

**Core question it answers:** "How many tokens does each part of my `~/.claude/` config
cost, and how much did that change after I edited my settings?"

It does this via repeatable **snapshots** of token counts across all config components,
plus **diffs** between any two snapshots. The default path is entirely free of charge.

---

## In Scope

- All files and sub-directories under `~/.claude/` — skills, agents, MCP tool schemas,
  `CLAUDE.md`, rules files, `settings.json`, and any additional memory files.
- Two measurement layers: static (free) and empirical (opt-in, budget-guarded).
- Snapshot storage, diffing, and human-readable + JSON reporting.
- Registration as the 4th app in the repo `apps.json` for AppLauncher integration.

## Out of Scope

- Measuring project-level `.claude/` directories (only global `~/.claude/`).
- Modifying, linting, or optimizing the user's config — read-only tool.
- A Textual TUI (deferred to Phase 4, optional).
- Any Claude API features beyond `count_tokens` and subprocess `claude -p` calls.

---

## Definitions

**`tokens_always_loaded`** — tokens contributed by a component that are present in
context on every Claude Code invocation regardless of what the user asks. Examples:
skill name + description line, agent description, full `CLAUDE.md`, each rules file,
MCP tool schemas.

**`tokens_invocation`** — tokens loaded only when a component is actively invoked
(e.g., the full body of a skill's `.md` file). For components that are always fully
loaded, this field equals `tokens_always_loaded` or is `null`.

**Empirical measurement** — running `claude -p "<trigger>"` and reading the `usage`
object from `--output-format json`. Produces real observed token counts. This is the
only measurement mode that spends the user's Claude subscription allowance.

---

## Measurement Mechanisms

### Layer 1 — Static Footprint (Primary, FREE)

Uses the Anthropic `count_tokens` endpoint:

```
client.messages.count_tokens(model=<model>, messages=[...])
```

`count_tokens` does **not** bill tokens and does **not** consume the user's rolling
4-hour generation allowance. It is the default measurement path.

Default model: `claude-opus-4-8` (token counts are model-specific; override with
`--model`).

**Prerequisite:** requires an `ANTHROPIC_API_KEY` (or equivalent SDK credential).
See Prerequisites section.

### Fallback — `claude -p` Baseline

If no Anthropic API key is available, ClaudeBench falls back to invoking
`claude -p "<minimal prompt>" --output-format json` and reading the `usage.input_tokens`
field as a proxy for total context size. This fallback **does** spend a small amount of
the subscription allowance per run and is clearly flagged in output
(`"tokenizer": "claude-p-fallback"`).

### Layer 2 — Empirical (Opt-In, SPENDS ALLOWANCE)

Invoked only via `bench` subcommand with explicit flags. Runs `claude -p "/skill-name"`
(or a derived trigger prompt) N times, reads `usage`, and reports mean + min/max.

**Cost boundary (stated explicitly):**
- Static (`list`, `snapshot`, `diff`) = **free** (count_tokens endpoint).
- Empirical (`bench`) = **spends the 4-hour subscription allowance**. Never runs
  unless explicitly requested. Always estimates cost first via free count_tokens,
  displays the estimate, and asks for confirmation before proceeding.

---

## Per-Component Metrics

Each discovered config component is classified by `kind`:

| Kind      | Examples                               | always_loaded content                        |
|-----------|----------------------------------------|----------------------------------------------|
| `skill`   | skills under `~/.claude/skills/`       | name + description line                      |
| `agent`   | agent definitions                      | agent description                            |
| `mcp`     | MCP tool schemas                       | full tool schema                             |
| `memory`  | `CLAUDE.md`, memory files              | full file body                               |
| `rule`    | files under `~/.claude/rules/`         | full file body                               |
| `setting` | `settings.json`                        | serialized JSON                              |

Each component records `tokens_always_loaded` and `tokens_invocation` (null if not
separately invocable). A `content_hash` (SHA-256) lets the differ distinguish a
renamed/new component from one whose content changed.

---

## Snapshot & Diff Model

### Snapshot

A snapshot is a point-in-time JSON record of all component token counts. The canonical
snapshot JSON shape:

```json
{
  "taken_at": "<ISO8601>",
  "label": "<string or null>",
  "config_dir": "<absolute path>",
  "model": "claude-opus-4-8",
  "tokenizer": "count_tokens | claude-p-fallback",
  "totals": {
    "always_loaded": 0,
    "invocation": 0,
    "by_kind": { "skill": 0, "agent": 0, "mcp": 0, "memory": 0, "rule": 0, "setting": 0 }
  },
  "components": [ /* see below */ ]
}
```

Each component entry:

```json
{
  "kind": "skill | agent | mcp | memory | rule | setting",
  "id": "<slug>",
  "name": "<display name>",
  "path": "<relative to config_dir>",
  "content_hash": "sha256:...",
  "tokens_always_loaded": 0,
  "tokens_invocation": 0,
  "empirical": null
}
```

The `empirical` field is `null` for static-only snapshots. When populated (via `bench`):

```json
"empirical": {
  "runs": 3,
  "input_mean": 0.0, "output_mean": 0.0,
  "input_min": 0, "input_max": 0,
  "output_min": 0, "output_max": 0,
  "budget_spent": 0
}
```

The **full machine-readable schema** lives in `snapshot.schema.json` at the repo root
of ClaudeBench.

### Diff

`diff` compares two snapshots by component `id` and `content_hash`. It reports:
- Added / removed components
- Components whose content changed (hash mismatch)
- Token delta (always_loaded and invocation) per component and in aggregate

Snapshots are stored under `snapshots/` (git-ignored).

---

## CLI Surface

Global flags (apply to all subcommands):

| Flag            | Default          | Notes                              |
|-----------------|------------------|------------------------------------|
| `--config-dir`  | `~/.claude`      | Path to scan                       |
| `--model`       | `claude-opus-4-8`| Model used for count_tokens        |
| `--json`        | off              | Emit machine-readable JSON output  |

### Subcommands

**`python claude_bench.py list`** — FREE
Scan `~/.claude/` and print each discovered component with its kind, name, path, and
static token counts. No snapshot is saved.

**`python claude_bench.py snapshot [--label NAME]`** — FREE
Run a full static measurement and save a timestamped snapshot file to `snapshots/`.
The optional `--label` annotates the snapshot for human reference.

**`python claude_bench.py diff [--from A] [--to B]`** — FREE
Compare two snapshots. `--from` and `--to` accept snapshot labels or timestamps.
Defaults to comparing the two most recent snapshots.

**`python claude_bench.py bench [--all | --skills a,b,c] [--runs 3] [--budget N] [--yes]`** — SPENDS ALLOWANCE
Run empirical measurement for specified components.
- `--all` targets every invocable component; `--skills` targets named skills only.
- `--runs` sets the number of invocations to average (default 3).
- `--budget N` sets a hard token ceiling; the run aborts if the estimate exceeds it.
- `--yes` skips the confirmation prompt (for scripted use).
- Without `--yes`, ClaudeBench always estimates cost via count_tokens first and prompts
  before spending any allowance.

---

## Budget Guard

The `bench` subcommand enforces a multi-step budget guard:

1. **Estimate** — use free count_tokens to estimate total input tokens across all
   targeted components and `--runs` repetitions.
2. **Display** — show the estimate (tokens + approximate subscription cost) and the
   `--budget` ceiling if set.
3. **Confirm** — require `--yes` or interactive `y/N` before proceeding.
4. **Guard** — abort mid-run if cumulative `budget_spent` exceeds `--budget`.
5. **Report** — after completion, report mean + min/max across runs per component.

Default behavior is static-only (no `bench` run unless explicitly invoked). The budget
guard cannot be bypassed except with `--yes` + `--budget` explicitly supplied.

---

## Phases

| Phase | Name               | Commands enabled            | Costs allowance? |
|-------|--------------------|-----------------------------|------------------|
| 0     | Prereqs & Scaffold | (none)                      | No               |
| 1     | Static MVP         | `list`, `snapshot`          | No               |
| 2     | Diff               | `diff`                      | No               |
| 3     | Empirical (opt-in) | `bench`                     | Yes (opt-in)     |
| 4     | Integration        | AppLauncher + optional TUI  | No               |

Phases 1 and 2 are the primary deliverable. Phase 3 is explicitly opt-in and
budget-guarded. Phase 4 wires the app into the repo's AppLauncher via `apps.json`.

---

## Module Layout

```
ClaudeBench/
  claude_bench.py          # Entry point + argparse
  claudebench/
    models.py              # Frozen dataclasses: Component, Snapshot, Diff
    scanner.py             # Walk ~/.claude/, classify components
    tokenizer.py           # count_tokens calls + claude-p fallback
    probe.py               # Phase 3: claude -p invocations + budget guard
    snapshot.py            # Save/load snapshot files
    differ.py              # Compare two Snapshot objects
    report.py              # Human-readable + JSON output formatters
  snapshots/               # Git-ignored runtime data
  snapshot.schema.json     # Machine-readable JSON schema for snapshot format
  requirements.txt
  docs/
```

Stack: Python 3.11+, `anthropic` SDK (pinned, pip-audit-clean), stdlib only beyond
that. All internal data structures use frozen dataclasses (immutability-first).

---

## Prerequisites & Open Items

- [x] Python 3.11+ available on the machine
- [x] `anthropic` SDK installable via pip; pin version in `requirements.txt`; pass
      `pip-audit` before committing
- [ ] **Confirm whether an Anthropic API key (`ANTHROPIC_API_KEY`) is available in the
      user's environment. If not, implement the `claude -p` baseline fallback as the
      primary tokenizer (small allowance cost per snapshot; flagged clearly in output).**
- [x] `claude` CLI available on PATH (required only for Phase 3 empirical and the
      `claude-p-fallback` tokenizer path)
- [x] `snapshots/` added to `.gitignore` before first run
