# ClaudePanes Development Guide

How to work on ClaudePanes itself: dev environment, code style, testing, commits, and doc updates. Written for the author returning after a break and for any future contributor.

ClaudePanes is a zero-dependency, single-file Python launcher (Python 3.11+, stdlib only) that reads a TOML layout config and opens the requested pane layout in whichever terminal multiplexer is installed.

## 1. Dev environment

- Python 3.11+ required. 3.12 or 3.13 recommended. CI matrix will test all three once stable.
- No virtualenv required for runtime (zero deps), but recommended for dev tools.
- Optional dev tools: `ruff` for lint and format. No test runner beyond stdlib `unittest`.
- Editor: any. The repo carries no editor-specific config.

Bootstrap a freshly cloned repo:

```bash
# 1. Verify Python
python --version   # >= 3.11

# 2. Run the tool directly (no install)
python claude_panes.py --help

# 3. Optional: set up a dev venv for lint/format tools
python -m venv .venv
.venv\Scripts\activate    # Windows
# .venv/bin/activate       # macOS/Linux
pip install ruff
```

The `.venv` directory is git-ignored. Do not commit it.

## 2. Repository layout

```
ClaudePanes/
├── claude_panes.py        # The tool. Single file. Stdlib only.
├── tests/                 # stdlib unittest cases (added in Phase 3)
│   └── test_*.py
├── docs/                  # All design docs (this file lives here)
├── examples/              # Example TOML layouts (added in Phase 1)
│   └── *.toml
├── README.md
├── PROGRESS.md
├── .gitignore
└── (no requirements.txt — zero deps)
```

If `claude_panes.py` exceeds ~600 lines, consider splitting (likely first cut: `adapters.py`, `config.py`). Until then, keep it single-file to preserve the "drop in and run" property.

## 3. Code style

- Pure stdlib. Never add a third-party dependency without an ADR in `design-decisions.md`.
- Python 3.11+ syntax is fair game: structural pattern matching, `tomllib`, `Self` type hints, exception groups, etc.
- Type hints required on public functions. Internal helpers can be looser.
- `from __future__ import annotations` at the top of every file.
- Black-compatible formatting via `ruff format` (or manual). Line length 100.
- Naming: `snake_case` for functions and variables, `PascalCase` for classes, `UPPER_SNAKE` for module-level constants.
- One module-level docstring per file. No file-wide license headers — `LICENSE` covers the whole repo.
- Comments: only when the *why* isn't obvious. Don't restate the code.
- No emojis in code or docs unless explicitly requested.

Lint and format before committing:

```bash
ruff check .
ruff format .
```

## 4. Testing

- Use stdlib `unittest`. No pytest. Adding it would violate ADR-003 (zero-dep posture).
- Test file naming: `tests/test_<module>.py`.
- Run all tests:

```bash
python -m unittest discover tests
```

- Aim for coverage on: config parsing, validation, and adapter command construction.
- Do not unit-test `subprocess.run` itself. Use `--dry-run` integration tests that assert on the constructed argv instead.
- Test data: small `.toml` fixtures under `tests/fixtures/`.

Example test pattern:

```python
import unittest
from pathlib import Path
from claude_panes import load_layout

class TestConfigLoad(unittest.TestCase):
    def test_minimal_pane(self):
        fixture = Path("tests/fixtures/minimal.toml")
        layout = load_layout(fixture)
        self.assertEqual(len(layout.panes), 1)
```

Keep fixtures minimal and named for the case they cover (`minimal.toml`, `four_pane_grid.toml`, `invalid_split_ratio.toml`).

## 5. Commits

Format:

```
<type>: <short description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

Body (optional): explain the *why*. The diff shows the *what*.

Examples:

```
feat: add windows terminal adapter
docs: clarify wsl invocation in config-format
fix: handle missing layouts dir in `list` subcommand
refactor: extract adapter detection into its own function
```

When this project picks up a ticket prefix (Jira, Linear, etc.), shift to `<type>(<TICKET-ID>): <description>`.

Subject line: imperative mood, lowercase first letter, no trailing period, target ~50 chars (hard cap 72).

## 6. Branching

- `main` is the trunk. Direct commits on `main` are fine during pre-MVP solo work.
- Once `v1.0` is tagged: feature branches plus PRs, even for solo work, to keep a clean history.
- Tag releases as `vX.Y.Z` following semver.

## 7. Pull requests (when applicable)

- PR title follows the commit subject style.
- PR body: bullet points under `## Summary`. No "test plan" section.

Template:

```markdown
## Summary
- What changed and why
- Notable trade-offs
- Linked docs updated
```

## 8. Adding a new terminal adapter

The repeatable extension point. Step-by-step:

1. Add a new entry to `terminal-adapters.md`: detection logic, command shape, platform quirks, smoke test command.
2. Add a class to `claude_panes.py` (or a future `adapters.py`) implementing the `Adapter` protocol from `architecture.md`.
3. Register the new adapter in the priority list (order matters: more specific or higher-fidelity adapters first).
4. Add a TOML fixture under `tests/fixtures/` and an integration test that runs with `--dry-run` and asserts on the constructed argv.
5. Update `PROGRESS.md` with a bullet noting the new adapter.

## 9. Updating docs

Doc placement rules for this project:

- Architectural changes — update `architecture.md` **and** add an ADR to `design-decisions.md`.
- New CLI commands or flags — update `cli-spec.md`.
- New TOML fields — update `config-format.md` **and** `usage-examples.md`.
- Anything user-facing — consider updating `README.md` and `usage-examples.md`.
- Every meaningful change — tick a checkbox or add a bullet in `PROGRESS.md`.

Docs live in `docs/`. Keep them short and operational; prefer code fences for any command or snippet.

## 10. Releasing

Placeholder. Flesh out at v1.0.

- Bump the version constant in `claude_panes.py`.
- Tag and push:

```bash
git tag v0.X.Y
git push --tags
```

- Future: PyPI release and `pipx`-installable single-file entry point.

## 11. Security disclosures

See `security.md` for the threat model.

For now, hobby-project response policy: open a GitHub issue (or contact the author directly for sensitive reports) before public disclosure. Response is best-effort; no SLA.
