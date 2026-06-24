# ClaudeBench

A Python CLI that measures and tracks the **token footprint** of your global
Claude Code config (`~/.claude/`). Run a snapshot before and after editing your
settings to see exactly what changed — and what it costs.

> **Not a Claude Code skill.** ClaudeBench is a standalone app that shells out
> to the `claude` CLI when needed; it does not run inside Claude Code itself.

---

## Free vs. allowance spend

| Mode | Cost | How |
|------|------|-----|
| Static (default) | **Free** — does NOT bill tokens or touch your 4-hour generation allowance | Anthropic `count_tokens` API |
| Empirical (`bench`) | **Spends your 4-hour allowance** — opt-in, budget-guarded, requires `--yes` | `claude -p "<trigger>"` averaged over N runs |

Default usage (`list`, `snapshot`, `diff`) is always free.

---

## Prerequisites

- Python 3.11+
- `anthropic` SDK (pinned in `requirements.txt`)
- **Anthropic API key** (`ANTHROPIC_API_KEY`) — needed for the free static path.
  If you don't have one, ClaudeBench falls back to `claude -p` baseline totals
  (uses your Claude subscription; small allowance cost per run).
  Set it persistently on Windows (user scope), then restart your terminal:
  `[Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', 'sk-ant-...', 'User')`

---

## Install

```powershell
cd ClaudeBench
pip install -r requirements.txt
```

---

## Quickstart

All commands accept global flags: `--config-dir` (default `~/.claude`),
`--model` (default `claude-opus-4-8`), `--json`.

### `list` — show config components (free)

Enumerate every component ClaudeBench found in `~/.claude/`.

```powershell
python claude_bench.py list
```

### `snapshot` — capture a token footprint (free)

Count tokens for every component and save the result to `snapshots/`.

```powershell
python claude_bench.py snapshot --label before-refactor
```

### `diff` — compare two snapshots (free)

Show what changed between two saved snapshots. Omit flags to compare the two
most recent.

```powershell
python claude_bench.py diff --from before-refactor --to after-refactor
```

### `bench` — empirical measurement (SPENDS allowance, opt-in)

Fire real `claude -p` invocations to measure actual loaded context. Requires
explicit `--yes` confirmation. Use `--budget N` to cap allowance consumption.

```powershell
python claude_bench.py bench --skills summarize,review --runs 3 --budget 50 --yes
```

---

## Example output

```
Component                    Type        Always (tok)   Invocation (tok)   Delta
---------------------------  ----------  -------------  -----------------  -----
CLAUDE.md                    rule              1 842               —          —
rules/common/coding-style    rule                310               —          —
rules/common/git-workflow    rule                228               —          —
agents/backend-engineer      agent               —              4 105         —
skills/commit-message        skill               —                612         —
settings.json                settings            184               —          —
---------------------------  ----------  -------------  -----------------  -----
TOTAL                                          2 564               4 717
```

---

## Snapshots

Snapshots are saved to `ClaudeBench/snapshots/` (git-ignored). Each snapshot is
a timestamped JSON file. Use `diff` to compare any two.

---

## Further reading

- [SPEC.md](SPEC.md) — measurement methodology, token-counting details, fallback
  behavior, and output schema.
- [ARCHITECTURE.md](ARCHITECTURE.md) — module layout, data flow, and extension
  points.
