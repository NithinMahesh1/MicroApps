"""editor.py — open a file in the user's editor (VS Code preferred).

UI-agnostic helper used by the Config tab: pressing Enter on a component opens its
source file. Prefers the VS Code CLI (``code`` / ``code-insiders``); falls back to
the OS default handler. ``dry_run`` returns the plan without launching (for tests).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Hide the transient console when launching VS Code's .cmd shim via cmd.exe.
_CREATE_NO_WINDOW = 0x08000000


def find_vscode() -> str | None:
    """Path to the VS Code (or Insiders) CLI launcher, or None if not installed."""
    return shutil.which("code") or shutil.which("code-insiders")


def open_in_editor(path: str | Path, *, dry_run: bool = False) -> dict:
    """Open ``path`` in VS Code if available, else the OS default application.

    Returns a plan dict ``{editor, target, argv}``. Raises ``FileNotFoundError`` when
    the path does not exist. With ``dry_run=True`` nothing is launched.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"no such file: {target}")

    code = find_vscode()
    if code is not None:
        # On Windows ``code`` is a .cmd shim; CreateProcess can't run it directly,
        # so route through cmd.exe (kept window-less via CREATE_NO_WINDOW).
        if code.lower().endswith((".cmd", ".bat")):
            argv = ["cmd", "/c", code, "--reuse-window", str(target)]
        else:
            argv = [code, "--reuse-window", str(target)]
        plan = {"editor": "vscode", "target": str(target), "argv": argv}
        if not dry_run:
            subprocess.Popen(argv, creationflags=_CREATE_NO_WINDOW)
        return plan

    plan = {"editor": "default", "target": str(target), "argv": None}
    if not dry_run:
        os.startfile(str(target))  # type: ignore[attr-defined]  # Windows only
    return plan
