"""Open the OS's native folder picker so the user can choose notes directories.

Used by the QuizMe "Notes folders…" dialog. Pure stdlib (subprocess); never
imports textual. The caller MUST invoke :func:`pick_directories` from a worker
thread — it blocks until the user closes the native dialog.

Back-ends, in preference order: ``zenity`` (GNOME/GTK), ``kdialog`` (KDE),
``yad``, ``qarma``. Multi-selection is honored where supported (zenity/yad/qarma);
kdialog returns a single directory. All print the chosen path(s) to stdout and
exit non-zero when the user cancels.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_TITLE = "Select study-notes folder(s)"
_TOOLS = ("zenity", "kdialog", "yad", "qarma")
_SEP = "\n"


class PickerUnavailable(RuntimeError):
    """No native folder-picker tool is installed (callers should fall back)."""


def picker_tool() -> str | None:
    """Return the first available native picker on PATH, or ``None``."""
    for name in _TOOLS:
        if shutil.which(name):
            return name
    return None


def available() -> bool:
    return picker_tool() is not None


def _argv(tool: str, start: Path) -> list[str]:
    """Build the dialog command for *tool*, starting at *start*."""
    if tool in ("zenity", "qarma"):
        return [tool, "--file-selection", "--directory", "--multiple",
                "--separator", _SEP, "--title", _TITLE, f"--filename={start}{os.sep}"]
    if tool == "yad":
        return [tool, "--file", "--directory", "--multiple",
                "--separator", _SEP, "--title", _TITLE, f"--filename={start}{os.sep}"]
    # kdialog: single directory only.
    return [tool, "--getexistingdirectory", str(start)]


def pick_directories(start: Path | None = None) -> list[Path]:
    """Open the native picker and return the chosen directories.

    Returns ``[]`` if the user cancels. Raises :class:`PickerUnavailable` when no
    picker tool is installed, so callers can fall back to manual path entry.
    """
    tool = picker_tool()
    if tool is None:
        raise PickerUnavailable("No native folder picker found (install zenity or kdialog).")
    start = start if start is not None else Path.home()
    try:
        proc = subprocess.run(_argv(tool, start), capture_output=True, text=True)
    except OSError as exc:  # pragma: no cover - tool vanished between which() and run()
        raise PickerUnavailable(str(exc)) from exc
    if proc.returncode != 0:        # user cancelled (or the dialog failed to open)
        return []
    return [Path(p) for p in proc.stdout.strip().split(_SEP) if p.strip()]
