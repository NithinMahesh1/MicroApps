"""Path-resolution utilities for the MicroApps Launcher.

All functions in this module are pure (no side-effects on inputs) and use
only the Python standard library.  They are the single source of truth for
turning repo-relative strings from ``apps.json`` into absolute
:class:`pathlib.Path` objects and for normalising command vectors before
subprocess execution.
"""
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from microapps_launcher.models import App


# ---------------------------------------------------------------------------
# Repo-root discovery
# ---------------------------------------------------------------------------


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up the directory tree and return the first dir that contains both
    ``apps.json`` **and** a ``.git`` entry.

    Parameters
    ----------
    start:
        Directory to begin the search.  Defaults to the directory that
        contains *this* file (``microapps_launcher/``).

    Returns
    -------
    Path
        Resolved absolute path of the repo root.

    Raises
    ------
    FileNotFoundError
        When no qualifying ancestor directory is found.
    """
    candidate: Path = (start or Path(__file__).parent).resolve()

    while True:
        if (candidate / "apps.json").exists() and (candidate / ".git").exists():
            return candidate

        parent = candidate.parent
        if parent == candidate:
            # Reached the filesystem root without finding a match.
            raise FileNotFoundError(
                "Could not locate a repo root (directory containing both "
                "'apps.json' and '.git') by walking up from "
                f"{start or Path(__file__).parent!r}."
            )
        candidate = parent


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def resolve_repo(root: Path, rel: str) -> Path:
    """Resolve a repo-relative path string to an absolute :class:`~pathlib.Path`.

    Forward-slash normalisation is applied before joining, so paths stored
    in ``apps.json`` work on Windows regardless of their original separator.

    Parameters
    ----------
    root:
        Absolute repo root as returned by :func:`find_repo_root`.
    rel:
        Repo-relative path string (forward- or back-slash, no ``..``
        required but allowed).

    Returns
    -------
    Path
        ``(root / normalised_rel).resolve()``
    """
    return (root / rel.replace("\\", "/")).resolve()


def resolve_cwd(root: Path, app: App) -> Path:
    """Return the resolved working-directory path for *app*.

    Equivalent to ``resolve_repo(root, app.cwd)``.

    Parameters
    ----------
    root:
        Absolute repo root.
    app:
        The :class:`~microapps_launcher.models.App` whose ``cwd`` field is
        resolved.
    """
    return resolve_repo(root, app.cwd)


def resolve_in_cwd(root: Path, app: App, rel: str) -> Path:
    """Resolve *rel* relative to *app*'s working directory.

    Used for ``launch.cmd[0]`` (when it is a path) and
    ``prepare.sentinel``.

    Parameters
    ----------
    root:
        Absolute repo root.
    app:
        Provides the base ``cwd``.
    rel:
        Path string relative to ``app.cwd``.
    """
    cwd = resolve_cwd(root, app)
    return (cwd / rel.replace("\\", "/")).resolve()


# ---------------------------------------------------------------------------
# Command-vector normalisation
# ---------------------------------------------------------------------------


def resolve_command(root: Path, app: App, cmd: Sequence[str]) -> list[str]:
    """Return a new argv list with the executable token normalised.

    Transformation rules (applied only to ``cmd[0]``):

    * ``"python"``  -> :data:`sys.executable`
    * ``"pip"``     -> ``[sys.executable, "-m", "pip"]``  (spliced in)
    * path-like (contains ``/`` or ``\\``, or ends with ``.exe``) ->
      :func:`resolve_in_cwd` result as a string
    * anything else -> unchanged (PATH lookup, e.g. ``dotnet``)

    The remainder of *cmd* is never modified.

    Parameters
    ----------
    root:
        Absolute repo root.
    app:
        Provides the ``cwd`` used by :func:`resolve_in_cwd`.
    cmd:
        Original command vector from the manifest.  Must be non-empty.

    Returns
    -------
    list[str]
        A brand-new list; *cmd* is never mutated.
    """
    if not cmd:
        return []

    head = cmd[0]
    tail = list(cmd[1:])

    if head == "python":
        return [sys.executable, *tail]

    if head == "pip":
        return [sys.executable, "-m", "pip", *tail]

    if "/" in head or "\\" in head or head.endswith(".exe"):
        return [str(resolve_in_cwd(root, app, head)), *tail]

    # Plain binary name — leave for PATH resolution.
    return [head, *tail]
