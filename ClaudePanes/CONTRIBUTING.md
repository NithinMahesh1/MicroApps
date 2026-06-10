# Contributing to ClaudePanes

Thanks for your interest in ClaudePanes. This document covers the essentials for getting set up and submitting changes. For deeper guidance on dev workflow, code style, and the doc structure, see [`docs/development-guide.md`](docs/development-guide.md).

## Quick start for contributors

ClaudePanes is a zero-runtime-dependency, single-file Python tool. There is nothing to install for the runtime itself.

```bash
# 1. Clone
git clone <TODO once published>
cd ClaudePanes

# 2. Verify Python (3.11 or newer)
python --version

# 3. Run the tool directly
python claude_panes.py --help

# 4. Run the test suite (stdlib unittest, no extra deps)
python -m unittest discover tests
```

CI runs the same `unittest discover` on Windows, Ubuntu, and macOS against Python 3.11, 3.12, and 3.13. If it passes locally on your platform, it will most likely pass in CI.

## Project layout

The repo is intentionally flat. `claude_panes.py` at the root is the entire tool (single file, stdlib only). `tests/` holds `unittest` cases and TOML fixtures. `examples/` carries sample layout TOMLs you can run against. `docs/` is the design and reference documentation (start with `architecture.md`, `cli-spec.md`, and `config-format.md`). `install.ps1` and `install.sh` are convenience installers for Windows and POSIX shells respectively.

## Making changes

### Branch naming

- `feat/<short-description>` for new functionality
- `fix/<short-description>` for bug fixes
- `docs/<short-description>` for documentation-only changes
- `refactor/`, `test/`, `chore/`, `perf/`, `ci/` follow the same pattern

### Commit message format

Matches the existing repo style:

```
<type>: <short description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

Subject line: imperative mood, lowercase first letter, no trailing period, target ~50 chars (hard cap 72). Optional body explains the *why*; the diff shows the *what*.

Examples:

```
feat: add windows terminal adapter
docs: clarify wsl invocation in config-format
fix: handle missing layouts dir in list subcommand
```

### Before pushing

1. Run the tests: `python -m unittest discover tests`
2. If you touched `claude_panes.py`, also sanity-check `python claude_panes.py --help` and at least one example layout from `examples/` with `--dry-run`.
3. Update relevant docs in `docs/` and tick the matching item in `PROGRESS.md`.

See [`docs/development-guide.md`](docs/development-guide.md) for the full workflow, including the adapter extension procedure and doc-placement rules.

## Architecture principles

One-line summaries; see [`docs/architecture.md`](docs/architecture.md) and [`docs/design-decisions.md`](docs/design-decisions.md) for the full story.

- **Zero runtime dependencies.** Stdlib only. New third-party deps require an ADR.
- **Single file.** `claude_panes.py` stays self-contained until it outgrows ~600 lines.
- **Frozen dataclasses.** Configuration and layout objects are immutable; transformations return new instances.
- **Adapters via `Protocol`.** Terminal multiplexers plug in behind a structural `Adapter` protocol so detection and dispatch stay decoupled from any specific terminal.

## Reporting bugs and requesting features

Please use the issue templates in [`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/):

- **Bug report** for reproducible defects. Include OS, Python version, terminal multiplexer and version, the TOML layout (or a minimal repro), and the exact command run.
- **Feature request** for new functionality. Describe the use case before the proposed solution.

For security-sensitive issues, see [`docs/security.md`](docs/security.md) and prefer private disclosure to the maintainer over a public issue.

## Code of Conduct

This project follows the [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to uphold its terms. Report unacceptable behavior to the maintainer at <TODO once published>.

## License

ClaudePanes is released under the MIT License. By contributing, you agree that your contributions will be licensed under the same terms. See [`LICENSE`](LICENSE).
