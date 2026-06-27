"""Spawn, track, and stop app processes according to their launch mode.

Cross-platform behaviour:

* **Windows** uses ``subprocess`` creation flags — ``CREATE_NEW_CONSOLE`` for a
  ``console`` app (its own console window) and ``DETACHED_PROCESS |
  CREATE_NO_WINDOW`` for ``fire-and-forget``.
* **POSIX (Linux/macOS)** has no such flags, so a ``console`` app is launched in
  a brand new terminal-emulator window via :mod:`microapps_launcher.terminal`.
  Otherwise it would inherit the launcher's own terminal and the two TUIs would
  corrupt each other (garbled display + an ``OSError: [Errno 5]`` on quit).
  ``fire-and-forget`` and ``gui`` apps are detached into their own session with
  their standard streams sent to ``/dev/null``.

Pure stdlib; imports cleanly on every OS (platform-specific calls are guarded).
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from microapps_launcher import paths, terminal
from microapps_launcher.models import App

_IS_WINDOWS = sys.platform.startswith("win")

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
        """Spawn *app* appropriately for its launch mode and host OS.

        ``console`` apps get their own window (a new console on Windows, a new
        terminal-emulator window on POSIX); ``fire-and-forget`` apps are detached
        and not tracked; ``gui`` apps run normally. ``extra_args`` are appended
        verbatim to the resolved command (used for launch-time picks, e.g. a
        ClaudePanes layout).

        Raises ``OSError`` (e.g. :class:`terminal.TerminalNotFound`) if the
        process cannot be started.
        """
        argv = paths.resolve_command(root, app, app.launch.cmd)
        if extra_args:
            argv = [*argv, *extra_args]
        cwd = str(paths.resolve_cwd(root, app))

        if _IS_WINDOWS:
            proc = self._spawn_windows(argv, cwd, app.launch_mode)
        else:
            proc = self._spawn_posix(argv, cwd, app.launch_mode)

        if app.launch_mode != "fire-and-forget":
            self._procs[app.id] = proc

    # -- platform spawners ---------------------------------------------------

    @staticmethod
    def _spawn_windows(argv: list[str], cwd: str, mode: str) -> subprocess.Popen:
        flags = 0
        if mode == "console":
            flags = _CREATE_NEW_CONSOLE
        elif mode == "fire-and-forget":
            flags = _DETACHED_PROCESS | _CREATE_NO_WINDOW
        return subprocess.Popen(argv, cwd=cwd, creationflags=flags)

    @staticmethod
    def _spawn_posix(argv: list[str], cwd: str, mode: str) -> subprocess.Popen:
        # A console app gets its OWN terminal window; everything else runs the
        # command directly. ``terminal.wrap`` may raise TerminalNotFound (an
        # OSError) when no terminal emulator is installed.
        spawn_argv = terminal.wrap(cwd, argv) if mode == "console" else argv
        # start_new_session detaches the child from the launcher's session and
        # controlling terminal; DEVNULL keeps any stray output (GTK warnings,
        # a terminal's own diagnostics) from corrupting the launcher's Textual
        # display. An app running inside a terminal window gets that window's
        # PTY for its I/O and is unaffected by these redirections.
        return subprocess.Popen(
            spawn_argv,
            cwd=cwd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # -- tracking ------------------------------------------------------------

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
            self._terminate(proc)
        self._procs.pop(app_id, None)

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        """SIGTERM then SIGKILL after a grace period.

        On POSIX the signal goes to the child's whole session/process group, so
        a terminal-launched app dies together with its terminal window (the app
        runs as a descendant of the terminal we spawned).
        """
        if _IS_WINDOWS:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            return

        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
