"""ClaudePanes - a zero-dependency Python launcher for multi-pane terminal layouts.

Reads a declarative TOML layout file and shells out to whichever supported
terminal multiplexer is installed on the host (Windows Terminal, WezTerm,
tmux, or Zellij) to open the requested tabs and pre-split panes running
pre-configured commands.

Single-file, Python 3.11+, standard library only. Designed for the
"parallel Claude Code sessions across git worktrees" workflow, but layout
agnostic: any command line that the host shell can run is fair game.

See docs/architecture.md, docs/cli-spec.md, and docs/config-format.md for
the design contracts this file implements.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


VERSION = "0.1.0"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "claude-panes"
ADAPTER_PRIORITY: tuple[str, ...] = ("wt", "wezterm", "tmux", "zellij")
SUPPORTED_TERMINALS = frozenset(ADAPTER_PRIORITY)
VALID_SPLITS = frozenset({"vertical", "horizontal"})

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_NO_TERMINAL = 3
EXIT_EXEC = 4

# Allowed-key sets for forward-compat warnings (per docs/config-format.md s6
# and docs/security.md s5: unknown keys warn, never abort).
_ALLOWED_TOP_KEYS = frozenset({
    "name", "description", "terminal", "working_dir", "shell", "panes", "tabs",
})
_ALLOWED_PANE_KEYS = frozenset({
    "cmd", "working_dir", "size", "split", "title", "parent",
})
_ALLOWED_TAB_KEYS = frozenset({"title", "panes"})
_ALLOWED_SHELL_KEYS = frozenset({"prelude"})


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ClaudePanesError(Exception):
    """Base class for all ClaudePanes errors. main() catches and maps these."""

    exit_code: int = EXIT_UNEXPECTED


class ConfigError(ClaudePanesError):
    """Raised when a layout file is missing, unparseable, or fails validation."""

    exit_code: int = EXIT_CONFIG


class NoTerminalError(ClaudePanesError):
    """Raised when no supported terminal is installed or the requested one is missing."""

    exit_code: int = EXIT_NO_TERMINAL


class ExecutionError(ClaudePanesError):
    """Raised when an adapter's subprocess invocation fails."""

    exit_code: int = EXIT_EXEC


def _warn_unknown_keys(data: dict, allowed: frozenset[str], scope: str) -> None:
    """Emit a UserWarning for every key in `data` that is not in `allowed`.

    Forward-compat per docs/config-format.md s6: unknown keys are warnings,
    not fatal errors, so a layout can carry future fields (see s8) without
    breaking older launchers."""
    for key in data:
        if key not in allowed:
            warnings.warn(
                f"unknown key {key!r} in {scope}; ignored", stacklevel=2
            )


# ---------------------------------------------------------------------------
# Layout model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pane:
    cmd: str
    title: str | None = None
    split: str | None = None  # "vertical" | "horizontal" | None for anchor
    size: float | None = None
    parent: int | None = None
    working_dir: str | None = None


@dataclass(frozen=True)
class Tab:
    title: str | None
    panes: tuple[Pane, ...]


@dataclass(frozen=True)
class Layout:
    name: str
    terminal: str | None
    working_dir: str | None
    shell_prelude: str
    tabs: tuple[Tab, ...]
    description: str | None = None


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def _validate_pane(data: dict, path: str, index: int) -> Pane:
    """Validate a single pane dict and return a Pane. `path` is the dotted key
    path for error messages (e.g. "tabs[0].panes[2])."""
    pane_path = f"{path}[{index}]"
    if not isinstance(data, dict):
        raise ConfigError(f"{pane_path} must be a table")

    _warn_unknown_keys(data, _ALLOWED_PANE_KEYS, pane_path)

    cmd = data.get("cmd")
    if not isinstance(cmd, str) or not cmd.strip():
        raise ConfigError(f"{pane_path}.cmd is required and must be a non-empty string")

    title = data.get("title")
    if title is not None and not isinstance(title, str):
        raise ConfigError(f"{pane_path}.title must be a string")

    split = data.get("split")
    if split is not None:
        if not isinstance(split, str) or split not in VALID_SPLITS:
            raise ConfigError(
                f"{pane_path}.split must be 'vertical' or 'horizontal', got {split!r}"
            )

    size = data.get("size")
    if size is not None:
        # tomllib accepts both ints and floats; coerce ints for convenience.
        if isinstance(size, bool) or not isinstance(size, (int, float)):
            raise ConfigError(f"{pane_path}.size must be a number")
        size = float(size)
        if not (0.0 < size < 1.0):
            raise ConfigError(
                f"{pane_path}.size must be strictly between 0 and 1, got {size}"
            )

    parent = data.get("parent")
    if parent is not None:
        if isinstance(parent, bool) or not isinstance(parent, int):
            raise ConfigError(f"{pane_path}.parent must be an integer")
        if parent < 0:
            raise ConfigError(f"{pane_path}.parent must be non-negative, got {parent}")
        if parent >= index:
            raise ConfigError(
                f"{pane_path}.parent ({parent}) must reference an earlier pane index"
            )

    working_dir = data.get("working_dir")
    if working_dir is not None and not isinstance(working_dir, str):
        raise ConfigError(f"{pane_path}.working_dir must be a string")

    # First pane in a tab: split has no meaning; drop it silently per the
    # config spec rather than warning, since the MVP has no warning channel.
    effective_split: str | None = split
    if index == 0:
        effective_split = None
        if parent is not None:
            raise ConfigError(f"{pane_path}.parent cannot be set on the first pane")
    else:
        if effective_split is None:
            effective_split = "vertical"  # documented default

    return Pane(
        cmd=cmd,
        title=title,
        split=effective_split,
        size=size,
        parent=parent,
        working_dir=working_dir,
    )


def _validate_panes(raw_panes: list, path: str) -> tuple[Pane, ...]:
    if not isinstance(raw_panes, list) or not raw_panes:
        raise ConfigError(f"{path} must contain at least one pane")
    return tuple(_validate_pane(p, path, i) for i, p in enumerate(raw_panes))


def _apply_prelude(panes: tuple[Pane, ...], prelude: str) -> tuple[Pane, ...]:
    if not prelude:
        return panes
    # Frozen dataclasses force rebuild rather than mutation (immutability rule).
    # Join with " && " so the pane command only runs if the prelude succeeds.
    return tuple(
        Pane(
            cmd=f"{prelude} && {p.cmd}",
            title=p.title,
            split=p.split,
            size=p.size,
            parent=p.parent,
            working_dir=p.working_dir,
        )
        for p in panes
    )


def load_layout(path: Path) -> Layout:
    """Parse and validate a TOML layout file. Raises ConfigError on any failure."""
    if not path.is_file():
        raise ConfigError(f"layout file not found: {path}")

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e
    except OSError as e:
        raise ConfigError(f"{path}: cannot read file: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top-level must be a table")

    _warn_unknown_keys(data, _ALLOWED_TOP_KEYS, f"{path}")

    name = data.get("name")
    if name is not None and not isinstance(name, str):
        raise ConfigError("'name' must be a string")
    if name is None:
        name = path.stem

    description = data.get("description")
    if description is not None and not isinstance(description, str):
        raise ConfigError("'description' must be a string")

    terminal = data.get("terminal")
    if terminal is not None:
        if not isinstance(terminal, str):
            raise ConfigError("'terminal' must be a string")
        if terminal not in SUPPORTED_TERMINALS:
            raise ConfigError(
                f"'terminal' must be one of {sorted(SUPPORTED_TERMINALS)}, got {terminal!r}"
            )

    working_dir = data.get("working_dir")
    if working_dir is not None and not isinstance(working_dir, str):
        raise ConfigError("'working_dir' must be a string")

    shell_table = data.get("shell", {})
    if not isinstance(shell_table, dict):
        raise ConfigError("'shell' must be a table")
    _warn_unknown_keys(shell_table, _ALLOWED_SHELL_KEYS, "shell")
    prelude = shell_table.get("prelude", "")
    if not isinstance(prelude, str):
        raise ConfigError("'shell.prelude' must be a string")

    has_panes = "panes" in data
    has_tabs = "tabs" in data
    if has_panes and has_tabs:
        raise ConfigError("layout cannot have both top-level [[panes]] and [[tabs]]")
    if not has_panes and not has_tabs:
        raise ConfigError("layout must have either [[panes]] or [[tabs]]")

    tabs: list[Tab]
    if has_panes:
        panes = _validate_panes(data["panes"], "panes")
        panes = _apply_prelude(panes, prelude)
        tabs = [Tab(title=None, panes=panes)]
    else:
        raw_tabs = data["tabs"]
        if not isinstance(raw_tabs, list) or not raw_tabs:
            raise ConfigError("'tabs' must contain at least one tab")
        tabs = []
        for i, t in enumerate(raw_tabs):
            tpath = f"tabs[{i}]"
            if not isinstance(t, dict):
                raise ConfigError(f"{tpath} must be a table")
            _warn_unknown_keys(t, _ALLOWED_TAB_KEYS, tpath)
            tab_title = t.get("title")
            if tab_title is not None and not isinstance(tab_title, str):
                raise ConfigError(f"{tpath}.title must be a string")
            tab_panes_raw = t.get("panes")
            if tab_panes_raw is None:
                raise ConfigError(f"{tpath}.panes is required")
            tab_panes = _validate_panes(tab_panes_raw, f"{tpath}.panes")
            tab_panes = _apply_prelude(tab_panes, prelude)
            tabs.append(Tab(title=tab_title, panes=tab_panes))

    return Layout(
        name=name,
        terminal=terminal,
        working_dir=working_dir,
        shell_prelude=prelude,
        tabs=tuple(tabs),
        description=description,
    )


def resolve_layout_path(layout_arg: str, config_dir: Path) -> Path:
    """Resolve a layout argument to an absolute path per cli-spec section 2.1."""
    if any(sep in layout_arg for sep in ("/", "\\")) or layout_arg.endswith(".toml"):
        return Path(layout_arg).expanduser().resolve()
    return (config_dir / "layouts" / f"{layout_arg}.toml").resolve()


# ---------------------------------------------------------------------------
# Terminal detection
# ---------------------------------------------------------------------------


def detect_terminal(override: str | None = None) -> str:
    """Return the chosen adapter name. Raises NoTerminalError if nothing usable
    is available. `override` honours an explicit user request before priority
    detection."""
    if override is not None:
        if override not in SUPPORTED_TERMINALS:
            raise NoTerminalError(
                f"unsupported terminal {override!r}; expected one of "
                f"{sorted(SUPPORTED_TERMINALS)}"
            )
        adapter = _adapter_for(override)
        if not adapter.is_available():
            raise NoTerminalError(
                f"terminal {override!r} requested but its binary "
                f"({adapter.binary}) was not found on PATH"
            )
        return override

    for name in ADAPTER_PRIORITY:
        if _adapter_for(name).is_available():
            return name
    raise NoTerminalError(
        "no supported terminal found on PATH; tried: " + ", ".join(ADAPTER_PRIORITY)
    )


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class Adapter(Protocol):
    name: str
    binary: str

    def is_available(self) -> bool: ...

    def build_command(self, layout: Layout) -> list[str]: ...

    def execute(
        self, layout: Layout, dry_run: bool = False, quiet: bool = False
    ) -> int: ...


def _run_argv(argv: list[str]) -> int:
    """Run an argv via subprocess.run. Translates failures into ExecutionError."""
    try:
        result = subprocess.run(argv, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        raise ExecutionError(f"failed to spawn {argv[0]}: {e}") from e
    if result.returncode != 0:
        raise ExecutionError(
            f"{argv[0]} exited with code {result.returncode}"
        )
    return result.returncode


def _format_argv(argv: list[str]) -> str:
    """Pretty-print argv for dry-run output. Uses list2cmdline on Windows so
    the printed form is paste-friendly into cmd.exe; POSIX shells get a
    shlex.join so `claude-panes start ... --dry-run | bash` works
    (docs/cli-spec.md s5)."""
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


class WindowsTerminalAdapter:
    name = "wt"
    binary = "wt"

    def is_available(self) -> bool:
        if sys.platform != "win32":
            return False
        return shutil.which("wt") is not None

    def build_command(self, layout: Layout) -> list[str]:
        # Always route through cmd.exe /c so wt's ';' sub-command separator
        # survives regardless of which shell launched ClaudePanes.
        argv: list[str] = ["cmd.exe", "/c", "wt.exe"]
        first_action = True
        for tab in layout.tabs:
            for pane_idx, pane in enumerate(tab.panes):
                if not first_action:
                    argv.append(";")
                first_action = False
                if pane_idx == 0:
                    argv.append("new-tab")
                    if tab.title:
                        argv += ["--title", tab.title]
                    if layout.working_dir:
                        argv += ["--startingDirectory", _expand(layout.working_dir)]
                    if pane.working_dir:
                        # Pane-level overrides tab-level.
                        argv += ["--startingDirectory", _expand(pane.working_dir)]
                    # Wrap cmd through `cmd.exe /c` at the wt boundary so the
                    # user's shell metacharacters (&&, |, quotes) survive
                    # verbatim; the user cmd is one opaque argv element
                    # (docs/security.md s4).
                    argv += ["--", "cmd.exe", "/c", pane.cmd]
                else:
                    argv.append("split-pane")
                    # wt's -V puts the new pane to the right (a vertical
                    # separator). The config spec says "vertical" == left/right
                    # division, so this maps 1:1.
                    argv.append("-V" if pane.split == "vertical" else "-H")
                    if pane.size is not None:
                        argv += ["-s", str(pane.size)]
                    if pane.title:
                        argv += ["--title", pane.title]
                    if pane.working_dir:
                        argv += ["--startingDirectory", _expand(pane.working_dir)]
                    argv += ["--", "cmd.exe", "/c", pane.cmd]
            # New tabs after the first use 'new-tab' again, which is what we
            # emit at the top of the loop for pane_idx == 0 — no per-tab
            # bookkeeping needed.
        return argv

    def execute(
        self, layout: Layout, dry_run: bool = False, quiet: bool = False
    ) -> int:
        argv = self.build_command(layout)
        if dry_run:
            # Banner on stderr, command on stdout: keeps `--dry-run | bash`
            # working per docs/cli-spec.md s5. `--quiet` suppresses the
            # informational banner but never the machine-readable argv.
            if not quiet:
                print("[wt adapter] Would execute:", file=sys.stderr)
            print(_format_argv(argv))
            return EXIT_OK
        return _run_argv(argv)


class WezTermAdapter:
    name = "wezterm"
    binary = "wezterm"

    def is_available(self) -> bool:
        return shutil.which("wezterm") is not None

    def build_command(self, layout: Layout) -> list[str]:
        # WezTerm uses multi-step execution with pane-id threading; there is
        # no single argv that realises a multi-pane layout.
        raise NotImplementedError("WezTermAdapter uses multi-step execute()")

    def execute(
        self, layout: Layout, dry_run: bool = False, quiet: bool = False
    ) -> int:
        for tab_idx, tab in enumerate(layout.tabs):
            pane_ids: list[str] = []
            for pane_idx, pane in enumerate(tab.panes):
                if pane_idx == 0:
                    argv = ["wezterm", "cli", "spawn"]
                    if tab_idx == 0:
                        argv.append("--new-window")
                    cwd = pane.working_dir or layout.working_dir
                    if cwd:
                        argv += ["--cwd", _expand(cwd)]
                    # Hand cmd to the user's shell unmodified so '&&', quotes,
                    # and backslashes survive (docs/security.md s4).
                    argv += ["--"] + _shell_wrap(pane.cmd)
                    pane_id = self._spawn_capturing_id(
                        argv, dry_run, quiet, placeholder=f"<id{tab_idx}-0>"
                    )
                else:
                    parent_idx = pane.parent if pane.parent is not None else pane_idx - 1
                    parent_id = pane_ids[parent_idx]
                    argv = [
                        "wezterm", "cli", "split-pane",
                        "--pane-id", parent_id,
                        _wezterm_direction(pane.split),
                    ]
                    if pane.size is not None:
                        argv += ["--percent", str(int(pane.size * 100))]
                    cwd = pane.working_dir or layout.working_dir
                    if cwd:
                        argv += ["--cwd", _expand(cwd)]
                    argv += ["--"] + _shell_wrap(pane.cmd)
                    pane_id = self._spawn_capturing_id(
                        argv, dry_run, quiet, placeholder=f"<id{tab_idx}-{pane_idx}>"
                    )
                pane_ids.append(pane_id)
        return EXIT_OK

    def _spawn_capturing_id(
        self, argv: list[str], dry_run: bool, quiet: bool, placeholder: str
    ) -> str:
        if dry_run:
            if not quiet:
                print("[wezterm adapter] Would execute:", file=sys.stderr)
            print(_format_argv(argv))
            return placeholder
        try:
            result = subprocess.run(argv, check=False, capture_output=True, text=True)
        except (OSError, subprocess.SubprocessError) as e:
            raise ExecutionError(f"failed to spawn wezterm: {e}") from e
        if result.returncode != 0:
            raise ExecutionError(
                f"wezterm exited with code {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout.strip()


class TmuxAdapter:
    name = "tmux"
    binary = "tmux"

    def is_available(self) -> bool:
        return shutil.which("tmux") is not None

    def build_command(self, layout: Layout) -> list[str]:
        # tmux models tabs as windows. Pane parent indexing maps to -t targets
        # using the {name}:{window}.{pane} addressing scheme, but for the MVP
        # we lean on tmux's "previous pane" default and only emit explicit
        # -t targets when `parent` is set.
        #
        # Append a millisecond suffix so re-running the same layout does not
        # collide with the previous session (docs/terminal-adapters.md s3).
        session = f"{layout.name}-{time.time_ns() // 1_000_000}"
        argv: list[str] = ["tmux"]
        first_tab = layout.tabs[0]
        first_pane = first_tab.panes[0]

        argv += ["new-session", "-d", "-s", session]
        if first_tab.title:
            argv += ["-n", first_tab.title]
        cwd = first_pane.working_dir or layout.working_dir
        if cwd:
            argv += ["-c", _expand(cwd)]
        argv.append(first_pane.cmd)

        for pane in first_tab.panes[1:]:
            argv.append(";")
            argv += ["split-window", "-t", session]
            argv.append("-h" if pane.split == "vertical" else "-v")
            if pane.size is not None:
                argv += ["-p", str(int(pane.size * 100))]
            pcwd = pane.working_dir or layout.working_dir
            if pcwd:
                argv += ["-c", _expand(pcwd)]
            argv.append(pane.cmd)

        for tab in layout.tabs[1:]:
            argv.append(";")
            argv += ["new-window", "-t", session]
            if tab.title:
                argv += ["-n", tab.title]
            anchor = tab.panes[0]
            acwd = anchor.working_dir or layout.working_dir
            if acwd:
                argv += ["-c", _expand(acwd)]
            argv.append(anchor.cmd)
            for pane in tab.panes[1:]:
                argv.append(";")
                argv += ["split-window", "-t", session]
                argv.append("-h" if pane.split == "vertical" else "-v")
                if pane.size is not None:
                    argv += ["-p", str(int(pane.size * 100))]
                pcwd = pane.working_dir or layout.working_dir
                if pcwd:
                    argv += ["-c", _expand(pcwd)]
                argv.append(pane.cmd)

        argv += [";", "attach", "-t", session]
        return argv

    def execute(
        self, layout: Layout, dry_run: bool = False, quiet: bool = False
    ) -> int:
        argv = self.build_command(layout)
        if dry_run:
            if not quiet:
                print("[tmux adapter] Would execute:", file=sys.stderr)
            print(_format_argv(argv))
            return EXIT_OK
        return _run_argv(argv)


class ZellijAdapter:
    name = "zellij"
    binary = "zellij"

    def is_available(self) -> bool:
        return shutil.which("zellij") is not None

    def build_command(self, layout: Layout) -> list[str]:
        kdl_path = self._write_kdl(layout)
        return ["zellij", "--layout", str(kdl_path)]

    def execute(
        self, layout: Layout, dry_run: bool = False, quiet: bool = False
    ) -> int:
        kdl = self._render_kdl(layout)
        if dry_run:
            if not quiet:
                print("[zellij adapter] Would write KDL layout:", file=sys.stderr)
                print(kdl, file=sys.stderr)
                print("[zellij adapter] Would execute:", file=sys.stderr)
            print("zellij --layout <generated.kdl>")
            return EXIT_OK
        # Use TemporaryDirectory so the parent dir is cleaned up too — the
        # previous unlink-only flow leaked the mkdtemp() parent. Zellij reads
        # the layout file at startup, so once `_run_argv` returns it is safe
        # to delete (docs/terminal-adapters.md s4 quirk 3).
        with tempfile.TemporaryDirectory(prefix="claudepanes-") as tmpdir:
            kdl_path = Path(tmpdir) / "layout.kdl"
            kdl_path.write_text(kdl, encoding="utf-8")
            return _run_argv(["zellij", "--layout", str(kdl_path)])

    def build_kdl(self, layout: Layout) -> str:
        """Public accessor used by tests; production callers should use
        `execute()` so the temp file is managed via a context manager."""
        return self._render_kdl(layout)

    def _write_kdl(self, layout: Layout) -> Path:
        return self._write_kdl_text(self._render_kdl(layout))

    def _write_kdl_text(self, kdl: str) -> Path:
        # Only used by `build_command()` for the test/inspection path; the
        # `execute()` happy path uses a TemporaryDirectory context manager
        # so production runs do not leak this dir. The dry-run flow does
        # not call this method at all.
        tmpdir = Path(tempfile.mkdtemp(prefix="claudepanes-"))
        kdl_path = tmpdir / "layout.kdl"
        kdl_path.write_text(kdl, encoding="utf-8")
        return kdl_path

    def _render_kdl(self, layout: Layout) -> str:
        lines: list[str] = ["layout {"]
        for tab in layout.tabs:
            tab_attrs = f' name="{_kdl_escape(tab.title)}"' if tab.title else ""
            lines.append(f"    tab{tab_attrs} {{")
            # For the MVP we use a single split_direction per tab based on the
            # second pane's split. Non-uniform pane trees would need nested
            # pane blocks; that is a documented Phase 2 enhancement.
            if len(tab.panes) == 1:
                lines.append(f"        {_kdl_pane_line(tab.panes[0])}")
            else:
                direction = _zellij_direction(tab.panes[1].split)
                lines.append(f'        pane split_direction="{direction}" {{')
                for pane in tab.panes:
                    lines.append(f"            {_kdl_pane_line(pane)}")
                lines.append("        }")
            lines.append("    }")
        lines.append("}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Adapter helpers
# ---------------------------------------------------------------------------


def _adapter_for(name: str) -> Adapter:
    match name:
        case "wt":
            return WindowsTerminalAdapter()
        case "wezterm":
            return WezTermAdapter()
        case "tmux":
            return TmuxAdapter()
        case "zellij":
            return ZellijAdapter()
        case _:
            raise NoTerminalError(f"no adapter for terminal {name!r}")


def _shell_wrap(cmd: str) -> list[str]:
    """Wrap an opaque shell-command string in the host shell invocation.

    Returns the argv suffix that runs `cmd` through the user's shell so
    that shell metacharacters (&&, |, quotes, backslashes) are honored.
    `cmd` is passed as a single argv element so it remains opaque to us;
    only the spawned shell parses it. On POSIX the user's login shell
    ($SHELL) is honored when set, falling back to /bin/sh otherwise.
    See docs/security.md s4."""
    if sys.platform == "win32":
        return ["cmd.exe", "/c", cmd]
    shell = os.environ.get("SHELL")
    if shell:
        return [shell, "-lc", cmd]   # honor the user's login shell (bash/zsh support -lc)
    return ["/bin/sh", "-c", cmd]    # POSIX fallback: -c only (dash has no -l)


def _expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def _wezterm_direction(split: str | None) -> str:
    # WezTerm: --right = side-by-side; --bottom = stacked.
    return "--right" if split == "vertical" else "--bottom"


def _zellij_direction(split: str | None) -> str:
    # Zellij: split_direction="vertical" means panes side-by-side (vertical
    # divider). Matches our config spec naming directly.
    return "vertical" if split == "vertical" else "horizontal"


def _kdl_escape(value: str) -> str:
    # Backslash MUST be replaced first so we don't double-escape the
    # backslashes introduced by the later replacements. Control chars are
    # escaped too (defense-in-depth: keeps every value on one KDL line and
    # avoids surprising a stricter KDL parser). See docs/security.md s4.
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _kdl_pane_line(pane: Pane) -> str:
    # Zellij requires structured argv — no shell wrapping. Hand the user's
    # opaque cmd to the local shell so '&&', quotes, and pipes survive
    # (docs/security.md s4). On Windows, route through `cmd.exe /c <cmd>`;
    # on POSIX, route through `bash -lc <cmd>` so login-shell rc files run.
    if sys.platform == "win32":
        command = "cmd.exe"
        shell_args = ["/c", pane.cmd]
    else:
        command = "bash"
        shell_args = ["-lc", pane.cmd]
    head = f'pane command="{_kdl_escape(command)}"'
    extras: list[str] = []
    joined = " ".join(f'"{_kdl_escape(a)}"' for a in shell_args)
    extras.append(f"args {joined}")
    if pane.size is not None:
        # Zellij interprets bare numbers as cells; we want percent of the
        # parent split so quote the value with a trailing '%'.
        extras.append(f'size "{int(pane.size * 100)}%"')
    body = "; ".join(extras)
    return f"{head} {{ {body} }}"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude-panes",
        description="Launch multi-pane terminal layouts described in TOML.",
        epilog=(
            "Config root defaults to ~/.config/claude-panes. See docs/cli-spec.md "
            "for the full specification."
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="suppress informational output")
    sub = parser.add_subparsers(dest="command", metavar="<subcommand>")

    p_start = sub.add_parser("start", help="open a layout in the host terminal")
    p_start.add_argument("layout", help="layout name or path to a .toml file")
    p_start.add_argument(
        "--terminal", choices=sorted(SUPPORTED_TERMINALS), help="override adapter selection"
    )
    p_start.add_argument("--dry-run", action="store_true", help="print command instead of running")
    p_start.add_argument("-v", "--verbose", action="store_true", help="log adapter selection")
    p_start.add_argument("--config-dir", type=Path, help="override config root")

    p_list = sub.add_parser("list", help="list known layouts")
    p_list.add_argument("--config-dir", type=Path, help="override config root")
    p_list.add_argument("--json", action="store_true", help="emit JSON output")

    p_validate = sub.add_parser("validate", help="validate a layout without executing")
    p_validate.add_argument("layout", help="layout name or path to a .toml file")
    p_validate.add_argument("--config-dir", type=Path, help="override config root")

    p_detect = sub.add_parser("detect", help="report installed terminals")
    p_detect.add_argument("--json", action="store_true", help="emit JSON output")

    sub.add_parser("version", help="print tool and interpreter versions")
    return parser


def _cmd_start(args: argparse.Namespace) -> int:
    config_dir = args.config_dir or DEFAULT_CONFIG_DIR
    layout_path = resolve_layout_path(args.layout, config_dir)
    layout = load_layout(layout_path)

    chosen = args.terminal or layout.terminal
    name = detect_terminal(chosen)
    adapter = _adapter_for(name)

    quiet = getattr(args, "quiet", False)
    # cli-spec.md s3: --quiet suppresses the verbose adapter log even when
    # --verbose was also passed (informational prose loses to explicit
    # silencing).
    if args.verbose and not quiet:
        print(f"[claude-panes] selected adapter: {name}", file=sys.stderr)
        print(f"[claude-panes] layout: {layout_path}", file=sys.stderr)

    return adapter.execute(layout, dry_run=args.dry_run, quiet=quiet)


def _cmd_list(args: argparse.Namespace) -> int:
    config_dir = args.config_dir or DEFAULT_CONFIG_DIR
    layouts_dir = config_dir / "layouts"
    if not layouts_dir.is_dir():
        raise ConfigError(f"layouts directory not found: {layouts_dir}")

    entries: list[dict[str, str | None]] = []
    for path in sorted(layouts_dir.glob("*.toml")):
        description: str | None = None
        try:
            with path.open("rb") as f:
                data = tomllib.load(f)
            raw = data.get("description")
            if isinstance(raw, str):
                description = raw
        except (tomllib.TOMLDecodeError, OSError):
            # Tolerate bad files in `list`; surface only via `validate`.
            description = None
        entries.append({"name": path.stem, "path": str(path), "description": description})

    if args.json:
        print(json.dumps(entries, indent=2))
    else:
        if entries:
            width = max(len(e["name"]) for e in entries)  # type: ignore[arg-type]
            for e in entries:
                desc = e["description"] or ""
                print(f"{e['name']:<{width}}  {desc}".rstrip())
    return EXIT_OK


def _cmd_validate(args: argparse.Namespace) -> int:
    config_dir = args.config_dir or DEFAULT_CONFIG_DIR
    path = resolve_layout_path(args.layout, config_dir)
    layout = load_layout(path)
    # cli-spec.md s3 calls out the `OK: <name>` line as informational prose
    # that --quiet suppresses; errors still surface via the raised ConfigError.
    if not getattr(args, "quiet", False):
        print(f"OK: {layout.name}")
    return EXIT_OK


def _cmd_detect(args: argparse.Namespace) -> int:
    results: dict[str, str | None] = {}
    for name in ADAPTER_PRIORITY:
        adapter = _adapter_for(name)
        if adapter.is_available():
            results[name] = shutil.which(adapter.binary)
        else:
            results[name] = None

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        width = max(len(n) for n in ADAPTER_PRIORITY)
        for name, location in results.items():
            value = location if location else "not found"
            print(f"{name:<{width}}  {value}")

    if not any(results.values()):
        raise NoTerminalError("no supported terminal installed")
    return EXIT_OK


def _cmd_version(_args: argparse.Namespace) -> int:
    print(f"claude-panes {VERSION}")
    print(f"python {sys.version.split()[0]}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_OK

    dispatch = {
        "start": _cmd_start,
        "list": _cmd_list,
        "validate": _cmd_validate,
        "detect": _cmd_detect,
        "version": _cmd_version,
    }

    try:
        return dispatch[args.command](args)
    except ClaudePanesError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_UNEXPECTED
    except Exception as e:  # last-resort guard at the top of main
        print(f"unexpected error: {e}", file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":
    raise SystemExit(main())
