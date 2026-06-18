"""Discover the file choices for an app's launch-time argument picker.

When an app declares ``launch.argPicker`` (see :class:`models.ArgPicker`), the
user picks one file before launch and its path is appended to the launch
command. This module finds those files from two sources: files shipped with the
app (``glob``, relative to the app cwd) and optional user-provided files outside
the repo (``userGlob``, an absolute / ``~``-expanded glob). It is pure stdlib and
never imports ``textual`` so it can run headless.
"""
from __future__ import annotations

import glob as globlib
import os
from dataclasses import dataclass
from pathlib import Path

from microapps_launcher import paths
from microapps_launcher.models import App

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    tomllib = None


@dataclass(frozen=True)
class ArgChoice:
    """One selectable file.

    ``value`` is the path appended verbatim to the launch command (cwd-relative
    for repo files, absolute for user-provided files); ``label`` is the filename
    stem; ``description`` is surfaced when available.
    """

    value: str
    label: str
    description: str | None = None


def discover_choices(root: Path, app: App) -> list[ArgChoice]:
    """Return the files an app's ``argPicker`` offers, user files first.

    Two sources are merged (deduped by absolute path):

    * ``userGlob`` — user-provided files outside the repo (``~`` and ``$VAR`` /
      ``%VAR%`` expanded, matched against the filesystem). Passed as an absolute
      path so the target tool resolves them regardless of its working directory.
    * ``glob`` — files shipped with the app, relative to its ``cwd``. Passed as a
      cwd-relative path.

    Returns an empty list when the app has no picker or nothing matches. For
    ``.toml`` files a top-level ``description`` string is surfaced best-effort;
    any read or parse error degrades to no description (never raises).
    """
    picker = app.launch.arg_picker
    if picker is None:
        return []

    seen: set[Path] = set()
    choices: list[ArgChoice] = []

    # User-provided files first — these are the ones tailored to the machine.
    if picker.user_glob:
        pattern = os.path.expanduser(os.path.expandvars(picker.user_glob))
        for match in sorted(globlib.glob(pattern)):
            path = Path(match)
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            choices.append(
                ArgChoice(value=str(path), label=path.stem, description=_describe(path))
            )

    # Files shipped with the app, relative to its cwd.
    cwd = paths.resolve_cwd(root, app)
    for path in sorted(cwd.glob(picker.glob)):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        rel = path.relative_to(cwd).as_posix()
        choices.append(ArgChoice(value=rel, label=path.stem, description=_describe(path)))

    return choices


def _describe(path: Path) -> str | None:
    """Best-effort one-line description from a ``.toml`` file's top-level key."""
    if tomllib is None or path.suffix != ".toml":
        return None
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    value = data.get("description")
    return value if isinstance(value, str) else None
