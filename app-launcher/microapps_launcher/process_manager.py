"""Spawn, track, and stop app processes according to their launch mode."""
from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from microapps_launcher import paths
from microapps_launcher.models import App

# Windows process-creation flags (0 on platforms where they do not exist, so
# this module imports cleanly everywhere).
_CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
_DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProcessManager:
    """Tracks the processes the launcher has started (by app id)."""

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}

    def launch(self, root: Path, app: App, extra_args: Sequence[str] = ()) -> None:
        """Spawn *app* with the creation flags appropriate to its launch mode.

        ``console`` apps get their own interactive window; ``fire-and-forget``
        apps are detached and not tracked; ``gui`` apps run normally. Standard
        streams are never redirected. ``extra_args`` are appended verbatim to the
        resolved command (used for launch-time picks, e.g. a ClaudePanes layout).
        """
        argv = paths.resolve_command(root, app, app.launch.cmd)
        if extra_args:
            argv = [*argv, *extra_args]
        cwd = str(paths.resolve_cwd(root, app))

        flags = 0
        if app.launch_mode == "console":
            flags = _CREATE_NEW_CONSOLE
        elif app.launch_mode == "fire-and-forget":
            flags = _DETACHED_PROCESS | _CREATE_NO_WINDOW

        proc = subprocess.Popen(argv, cwd=cwd, creationflags=flags)

        if app.launch_mode != "fire-and-forget":
            self._procs[app.id] = proc

    def is_running(self, app_id: str) -> bool:
        proc = self._procs.get(app_id)
        return proc is not None and proc.poll() is None

    def status(self, app_id: str) -> str:
        """Return ``"running"`` or ``"stopped"`` for a tracked app."""
        return "running" if self.is_running(app_id) else "stopped"

    def stop(self, app_id: str) -> None:
        """Gracefully terminate a tracked process, escalating to kill."""
        proc = self._procs.get(app_id)
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        self._procs.pop(app_id, None)
