# Code Walkthrough

A five-to-ten-minute orientation to `claude_panes.py`. The file is a single,
standard-library-only Python module organised as a vertical slice from CLI
parsing down to terminal-specific argv construction.

Line numbers in this document are deliberately approximate. The source file is
under active development; treat ranges as "find this section by scrolling near
here" rather than as stable addresses.

## 1. High-level layout

The file reads top-to-bottom as a single pipeline:

```
__main__ -> main() -> _build_parser() -> _cmd_* handler
                                            |
                                            v
                              resolve_layout_path() -> load_layout()
                                            |
                                            v
                              detect_terminal() -> _adapter_for()
                                            |
                                            v
                                  Adapter.execute(layout, dry_run=...)
                                            |
                                            v
                                       subprocess.run
```

Within the file the sections appear in this order:

1. Module docstring and imports (top).
2. Module-level constants: `VERSION`, `DEFAULT_CONFIG_DIR`,
   `ADAPTER_PRIORITY`, `SUPPORTED_TERMINALS`, `VALID_SPLITS`, exit codes, and
   allowed-key sets.
3. Exception hierarchy.
4. Layout model (`Pane`, `Tab`, `Layout`).
5. Config loader (`_validate_pane`, `_validate_panes`, `_apply_prelude`,
   `load_layout`, `resolve_layout_path`).
6. Terminal detection (`detect_terminal`).
7. Adapter `Protocol` plus four concrete adapters.
8. Adapter helpers (`_adapter_for`, `_shell_wrap`, direction maps, KDL helpers).
9. CLI: `_build_parser`, `_cmd_*` handlers, `main`.

## 2. Module sections

### Imports and constants (around lines 1-55)

Standard library only: `argparse`, `json`, `os`, `shlex`, `shutil`,
`subprocess`, `sys`, `tempfile`, `time`, `tomllib`, `warnings`. Constants
include the adapter priority order, the supported-terminal set, the
exit-code numbering documented in `docs/cli-spec.md`, and the allowed-key
frozensets used for forward-compatible "unknown key" warnings.

### Error types (around lines 60-100)

`ClaudePanesError` is the base class with a class-level `exit_code`.
`ConfigError`, `NoTerminalError`, and `ExecutionError` extend it with
specific exit codes. `main()` catches any `ClaudePanesError`, prints the
message, and returns the embedded exit code.

### Layout dataclasses (around lines 100-130)

`Pane`, `Tab`, and `Layout` are all `@dataclass(frozen=True)`. They are
constructed once during validation and never mutated. The `_apply_prelude`
helper demonstrates the immutability rule: it rebuilds each `Pane` with a
new `cmd` rather than touching the originals.

### Config loader (around lines 135-325)

`load_layout(path)` is the entry point: it opens the file with `tomllib`,
calls `_warn_unknown_keys` for forward compatibility, validates top-level
fields, then dispatches to `_validate_panes` for either a top-level
`[[panes]]` or each `[[tabs]]` entry. `_validate_pane` enforces per-pane
rules (non-empty `cmd`, `split` membership, `0 < size < 1`,
`parent < index`). `resolve_layout_path` implements the
"name vs path" disambiguation from `docs/cli-spec.md` section 2.1.

### Adapter protocol and adapters (around lines 360-660)

`Adapter` is a `typing.Protocol` with `name`, `binary`, `is_available()`,
`build_command()`, and `execute()`. Four concrete implementations follow:
`WindowsTerminalAdapter` (single `wt` argv with `;` separators),
`WezTermAdapter` (multi-step spawn capturing pane IDs from stdout),
`TmuxAdapter` (`new-session` plus chained `split-window` / `new-window`),
and `ZellijAdapter` (generates a KDL layout file in a
`TemporaryDirectory`). Helpers below the adapters handle shell wrapping
(`_shell_wrap`), path expansion (`_expand`), direction translation
(`_wezterm_direction`, `_zellij_direction`), and KDL escaping.

### CLI command handlers (around lines 740-860)

`_build_parser()` defines five subcommands: `start`, `list`, `validate`,
`detect`, `version`. Each `_cmd_*` handler is small and delegates to the
loader and adapter layers. `_cmd_start` is the only one that builds an
adapter and executes; `_cmd_validate` stops after `load_layout` succeeds;
`_cmd_list` tolerates malformed files (`list` should not abort on a
broken neighbour); `_cmd_detect` reports adapter availability.

### `main()` (around lines 860-890)

Builds the parser, parses argv, dispatches to a handler via a dict
lookup, and wraps everything in a try/except that converts
`ClaudePanesError` into a printed message plus exit code, with a
last-resort `Exception` guard for anything unexpected.

## 3. Where to start when adding...

### A new TOML field

1. Add the key to the relevant `_ALLOWED_*_KEYS` frozenset so it stops
   warning.
2. Add the field to the matching frozen dataclass (`Pane`, `Tab`, or
   `Layout`).
3. Validate the value inside `_validate_pane` or `load_layout`.
4. Thread the field through `_apply_prelude` if it lives on `Pane`.
5. Read it in whichever `Adapter.build_command` / `execute` needs it and
   emit the right terminal-specific argv flag.
6. Update `docs/config-format.md`.

### A new terminal adapter

1. Add a class implementing the `Adapter` protocol: `name`, `binary`,
   `is_available()`, `build_command()`, `execute()`.
2. Register it in `_adapter_for()` (`match` statement).
3. Add its name to `ADAPTER_PRIORITY` in the right priority slot.
4. Add it to the `choices` for `--terminal` (this is driven by
   `SUPPORTED_TERMINALS`, which is derived from `ADAPTER_PRIORITY`, so
   no extra change is needed).
5. Document quirks in `docs/terminal-adapters.md`.

### A new subcommand

1. Add a `sub.add_parser(...)` block in `_build_parser()`.
2. Write a `_cmd_<name>(args)` function returning an int exit code.
3. Register it in the `dispatch` dict inside `main()`.
4. Document it in `docs/cli-spec.md`.

## 4. Cross-references

This walkthrough is intentionally light on contracts and rationale. For the
actual specifications and design reasoning see:

- `docs/architecture.md` for the layered design and module boundaries.
- `docs/cli-spec.md` for the full CLI surface, exit codes, and resolution
  rules.
- `docs/config-format.md` for the authoritative TOML schema and
  forward-compatibility policy.
- `docs/terminal-adapters.md` for adapter-specific quirks and the
  argv-construction contract.
- `docs/development-guide.md` for setup, test commands, and the
  contribution workflow.
