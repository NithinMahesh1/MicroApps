"""editor.py — open a file in the user's editor (VS Code preferred).

UI-agnostic helper used by the Config tab: pressing Enter on a component opens its
source file. Prefers the VS Code CLI (``code`` / ``code-insiders``) and otherwise
falls back to the OS default file handler. Works on Windows, Linux, and macOS.
``dry_run`` returns the plan without launching anything (for tests).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows-only CreateProcess flag that hides the transient console window spawned
# when we launch VS Code's .cmd shim through cmd.exe. ``creationflags`` accepts only
# Windows process-creation constants, so this must NEVER be passed to subprocess on
# POSIX (where it would be meaningless / rejected).
_CREATE_NO_WINDOW = 0x08000000


def find_vscode() -> str | None:
    """Path to the VS Code (or Insiders) CLI launcher, or None if not installed.

    ``shutil.which`` is platform-aware: on Windows it resolves the ``code.cmd`` shim
    (honouring PATHEXT); on Linux/macOS it resolves the real ``code`` executable.
    """
    return shutil.which("code") or shutil.which("code-insiders")


def open_in_editor(path: str | Path, *, dry_run: bool = False) -> dict:
    """Open ``path`` in VS Code if available, else the OS default application.

    Cross-platform (Windows / Linux / macOS). Returns a plan dict
    ``{editor, target, argv}`` where ``argv`` is the command vector that would run, or
    ``None`` for the Windows ``os.startfile`` fallback (which takes no argv). Raises
    ``FileNotFoundError`` when ``path`` does not exist. With ``dry_run=True`` the plan
    is returned but nothing is launched.

    The platform is detected dynamically (``os.name`` / ``sys.platform``) at call time
    so the launch decision stays correct — and unit-testable via monkeypatching.
    """
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"no such file: {target}")

    is_windows = os.name == "nt"

    code = find_vscode()
    if code is not None:
        # On Windows ``code`` resolves to a .cmd/.bat shim that CreateProcess cannot
        # execute directly, so we route it through cmd.exe (kept window-less via
        # CREATE_NO_WINDOW). On Linux/macOS ``code`` is a real binary we exec
        # directly — no cmd wrapper and no Windows-only creationflags.
        if is_windows and code.lower().endswith((".cmd", ".bat")):
            argv = ["cmd", "/c", code, "--reuse-window", str(target)]
        else:
            argv = [code, "--reuse-window", str(target)]
        plan = {"editor": "vscode", "target": str(target), "argv": argv}
        if not dry_run:
            _spawn(argv, is_windows=is_windows)
        return plan

    # No VS Code installed: defer to the OS default file handler.
    if is_windows:
        # ``os.startfile`` exists ONLY on Windows (AttributeError on POSIX), so it is
        # guarded behind this branch rather than called unconditionally. It launches
        # via the shell association and takes no argv, hence ``argv: None``.
        plan = {"editor": "default", "target": str(target), "argv": None}
        if not dry_run:
            os.startfile(str(target))  # type: ignore[attr-defined]  # Windows only
        return plan

    # POSIX default handler: macOS ships ``open``, other Unixes use ``xdg-open``.
    # Both accept an argv vector, so the plan stays inspectable and testable.
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    argv = [opener, str(target)]
    plan = {"editor": "default", "target": str(target), "argv": argv}
    if not dry_run:
        _spawn(argv, is_windows=is_windows)
    return plan


def _spawn(argv: list[str], *, is_windows: bool) -> None:
    """Launch ``argv`` detached, applying the console-hiding flag only on Windows.

    ``creationflags`` is a Windows-only subprocess argument, so on POSIX we spawn
    without it.
    """
    if is_windows:
        subprocess.Popen(argv, creationflags=_CREATE_NO_WINDOW)
    else:
        subprocess.Popen(argv)
