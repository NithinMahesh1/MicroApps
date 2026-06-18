# ClaudeBench — Sample Report

This file shows what ClaudeBench's three report commands produce when run against a typical `~/.claude/` config.

_All numbers below are illustrative._

---

### `claude_bench.py snapshot`

Counts tokens for every component in `~/.claude/` using the Anthropic `count_tokens` endpoint (model `claude-opus-4-8`). No tokens are spent from your 4-hour allowance.

| Kind   | Id                      | tokens_always_loaded | tokens_invocation |
|--------|-------------------------|---------------------:|------------------:|
| memory | CLAUDE.md               |                  320 |                 — |
| rule   | common/coding-style     |                  112 |                 — |
| rule   | common/development-workflow |               98 |                 — |
| rule   | common/git-workflow     |                  145 |                 — |
| rule   | common/security         |                  110 |                 — |
| skill  | commit-message          |                   52 |               310 |
| skill  | explain-code            |                   88 |               640 |
| skill  | explain-simply          |                  130 |               720 |
| skill  | deep-research           |                  160 |             1,180 |
| skill  | pr-description          |                   74 |               420 |
| skill  | weekly-status           |                   48 |               540 |
| agent  | backend-engineer        |                  310 |               490 |
| agent  | code-reviewer           |                   62 |               280 |
| mcp    | atlassian/tool-schemas  |                  480 |                 — |

**Totals**

| Metric                  |       Count |
|-------------------------|------------:|
| total always_loaded     |       2,189 |
| total invocation        |       4,580 |
| components measured     |          14 |

By-kind always_loaded breakdown:

| Kind   | tokens_always_loaded |
|--------|---------------------:|
| memory |                  320 |
| rule   |                  465 |
| skill  |                  552 |
| agent  |                  372 |
| mcp    |                  480 |

---

### `claude_bench.py diff` (vs previous snapshot)

Compares the current snapshot against the last saved baseline. Reads no live tokens and spends nothing.

```
+ skill  weekly-status          +48 always  /  +540 invocation    [NEW]
~ rule   common/security        +18 always  /   n/a invocation    [CHANGED — content edited]
~ skill  explain-simply         +12 always  /   +80 invocation    [CHANGED — body expanded]
- skill  review-message          -66 always /  -410 invocation    [REMOVED]
```

| Metric           |  Delta |
|------------------|-------:|
| always_loaded    |    +12 |
| invocation       |   +210 |

Net change: always_loaded **+12**, invocation **+210** across 4 changed components.

---

### `claude_bench.py bench --skills deep-research,explain-simply --runs 3`

> **This is the only command that spends from your 4-hour Claude API allowance.**
> It calls `claude -p` with each skill invoked N times and records actual input/output tokens from the API response.

| Skill          | runs | input_mean | output_mean | input_min–max     | output_min–max  |
|----------------|-----:|-----------:|------------:|-------------------|-----------------|
| deep-research  |    3 |     47,210 |         842 | 46,880 – 47,540   | 790 – 910       |
| explain-simply |    3 |      2,970 |         318 | 2,910 – 3,020     | 290 – 355       |

Budget: estimated ~150k tokens, spent 150,630 / cap 200,000 tokens (75 % of cap used).

Empirical run completed in 4 m 12 s across 6 total API calls (3 runs × 2 skills).
