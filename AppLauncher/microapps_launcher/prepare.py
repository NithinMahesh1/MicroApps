"""Build-once 'prepare' step handling (sentinel check + streamed execution)."""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from microapps_launcher import paths
from microapps_launcher.models import App


def needs_prepare(root: Path, app: App) -> bool:
    """True if *app* has a prepare step that has not yet been satisfied."""
    if app.prepare is None:
        return False
    if not app.prepare.sentinel:
        return True
    return not paths.resolve_in_cwd(root, app, app.prepare.sentinel).exists()


def run_prepare(
    root: Path,
    app: App,
    on_line: Callable[[str], None] | None = None,
) -> int:
    """Run *app*'s prepare command, streaming output to *on_line*.

    Returns the process exit code (0 when nothing needs preparing).
    """
    if app.prepare is None or not needs_prepare(root, app):
        return 0

    argv = paths.resolve_command(root, app, app.prepare.cmd)
    cwd = str(paths.resolve_cwd(root, app))
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.stdout is not None:
        for line in proc.stdout:
            if on_line is not None:
                on_line(line.rstrip("\n"))
    return proc.wait()
