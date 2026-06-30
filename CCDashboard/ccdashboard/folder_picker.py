"""Open the OS's native folder picker so the user can choose notes directories.

Used by the QuizMe "Notes folders…" dialog. Pure stdlib (subprocess); never
imports textual. The caller MUST invoke :func:`pick_directories` from a worker
thread — it blocks until the user closes the native dialog.

Back-ends, in platform-native-first preference order:

* **Windows** — ``powershell`` / ``pwsh`` (WinForms ``FolderBrowserDialog``)
* **macOS** — ``osascript`` (AppleScript ``choose folder``)
* **Linux / POSIX** — ``zenity``, ``kdialog``, ``yad``, ``qarma`` (GTK/Qt dialogs)

All back-ends print the chosen path(s) to stdout, one per line, and exit
non-zero when the user cancels. Multi-selection is honored by all backends
except ``kdialog`` (single directory only).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_TITLE = "Select study-notes folder(s)"
_SEP = "\n"

_LINUX_TOOLS = ("zenity", "kdialog", "yad", "qarma")

# PowerShell script (Windows) — MUST run under -STA thread model for WinForms.
# Double-braced {{ / }} produce literal { / } after Python's str.format().
_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog; "
    "$dlg.Description = '{title}'; "
    "$dlg.SelectedPath = '{start}'; "
    "if ($dlg.ShowDialog() -eq 'OK') "
    "{{ Write-Output $dlg.SelectedPath; exit 0 }} "
    "else {{ exit 1 }}"
)

# AppleScript (macOS) — choose folder with multiple selections allowed.
# Outputs one POSIX path per line; user cancel raises error -128 so osascript
# exits non-zero, which the existing returncode != 0 guard turns into [].
_AS_SCRIPT = (
    "set chosen to choose folder "
    'with prompt "{title}" with multiple selections allowed\n'
    "set NL to ASCII character 10\n"
    'set out to ""\n'
    "repeat with f in chosen\n"
    "    set out to out & (POSIX path of f) & NL\n"
    "end repeat\n"
    "return out"
)


class PickerUnavailable(RuntimeError):
    """No native folder-picker tool is installed (callers should fall back)."""


def _ordered_tools() -> list[str]:
    """Return candidate tool names in platform-native-first order.

    Discovery is capability-based (``shutil.which``) so it works on any
    machine regardless of OS version or distro.
    """
    if sys.platform.startswith("win"):
        # Prefer the Windows-native backend; fall back to GTK/Qt tools (e.g.
        # WSL-bridged) then osascript as a last resort (never present on real
        # Windows, but included so unit tests can exercise the backend on any
        # platform by monkeypatching which()).
        return ["powershell", "pwsh"] + list(_LINUX_TOOLS) + ["osascript"]
    if sys.platform == "darwin":
        return ["osascript"] + list(_LINUX_TOOLS) + ["powershell", "pwsh"]
    # Linux / other POSIX
    return list(_LINUX_TOOLS) + ["powershell", "pwsh", "osascript"]


def picker_tool() -> str | None:
    """Return the first available native picker on PATH, or ``None``."""
    for name in _ordered_tools():
        if shutil.which(name):
            return name
    return None


def available() -> bool:
    return picker_tool() is not None


def _argv(tool: str, start: Path) -> list[str]:
    """Build the dialog command for *tool*, starting at *start*."""
    if tool in ("powershell", "pwsh"):
        # Escape embedded single quotes for PowerShell string literals.
        title = _TITLE.replace("'", "''")
        start_s = str(start).replace("'", "''")
        script = _PS_SCRIPT.format(title=title, start=start_s)
        return [tool, "-NoProfile", "-STA", "-Command", script]
    if tool == "osascript":
        title = _TITLE.replace('"', '\\"')
        script = _AS_SCRIPT.format(title=title)
        return [tool, "-e", script]
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
