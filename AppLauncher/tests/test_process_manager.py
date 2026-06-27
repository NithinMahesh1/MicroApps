"""Tests for ``microapps_launcher.process_manager`` cross-platform spawning.

Pure engine test (no textual). Fakes ``subprocess.Popen`` so nothing is really
spawned, and flips the module's ``_IS_WINDOWS`` flag to exercise both branches.
Runnable under pytest or standalone (``python tests/test_process_manager.py``).
"""
from __future__ import annotations

import signal
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microapps_launcher import process_manager
from microapps_launcher.models import App, Launch

ROOT = Path("/repo")


def _app(mode: str, cmd=("echo", "hi"), app_id: str = "x") -> App:
    return App(
        id=app_id, name="X", description="d", stack="python", cwd=".",
        launch=Launch(cmd=tuple(cmd)), launch_mode=mode, stoppable=True,
    )


class FakePopen:
    def __init__(self, argv, **kwargs) -> None:
        self.argv = list(argv)
        self.kwargs = kwargs
        self.pid = 4242
        self._poll: int | None = None

    def poll(self):
        return self._poll

    def wait(self, timeout=None):
        if self._poll is not None:
            return self._poll
        raise subprocess.TimeoutExpired(self.argv, timeout)

    def terminate(self):
        self._poll = 0          # model a process that exits on SIGTERM

    def kill(self):
        self._poll = -9


@contextmanager
def _patch(is_windows: bool, wrap_result=None, wrap_raises: BaseException | None = None):
    real_popen = process_manager.subprocess.Popen
    real_iswin = process_manager._IS_WINDOWS
    real_wrap = process_manager.terminal.wrap
    created: list[FakePopen] = []

    def fake_popen(argv, **kwargs):
        created.append(FakePopen(argv, **kwargs))
        return created[-1]

    def fake_wrap(cwd, argv):
        if wrap_raises is not None:
            raise wrap_raises
        return wrap_result if wrap_result is not None else ["TERM", "--", *argv]

    process_manager.subprocess.Popen = fake_popen
    process_manager._IS_WINDOWS = is_windows
    process_manager.terminal.wrap = fake_wrap
    try:
        yield created
    finally:
        process_manager.subprocess.Popen = real_popen
        process_manager._IS_WINDOWS = real_iswin
        process_manager.terminal.wrap = real_wrap


def test_posix_console_opens_terminal_and_is_tracked() -> None:
    with _patch(False, wrap_result=["ptyxis", "--", "echo", "hi"]) as created:
        pm = process_manager.ProcessManager()
        pm.launch(ROOT, _app("console"))
        assert created[0].argv == ["ptyxis", "--", "echo", "hi"]   # wrapped
        kw = created[0].kwargs
        assert kw["start_new_session"] is True
        assert kw["stdin"] == kw["stdout"] == kw["stderr"] == subprocess.DEVNULL
        assert pm.status("x") == "running"                          # tracked


def test_posix_fire_and_forget_is_detached_and_untracked() -> None:
    with _patch(False) as created:
        pm = process_manager.ProcessManager()
        pm.launch(ROOT, _app("fire-and-forget"))
        assert created[0].argv == ["echo", "hi"]                    # NOT wrapped
        assert created[0].kwargs["start_new_session"] is True
        assert pm.status("x") == "stopped"                          # not tracked


def test_posix_gui_is_tracked_but_not_wrapped() -> None:
    with _patch(False) as created:
        pm = process_manager.ProcessManager()
        pm.launch(ROOT, _app("gui"))
        assert created[0].argv == ["echo", "hi"]
        assert pm.status("x") == "running"


def test_posix_console_without_terminal_raises_oserror() -> None:
    from microapps_launcher.terminal import TerminalNotFound
    with _patch(False, wrap_raises=TerminalNotFound("none")):
        pm = process_manager.ProcessManager()
        try:
            pm.launch(ROOT, _app("console"))
        except OSError:
            pass
        else:
            raise AssertionError("expected the TerminalNotFound to propagate")


def test_windows_console_uses_creationflags_not_session() -> None:
    with _patch(True) as created:
        pm = process_manager.ProcessManager()
        pm.launch(ROOT, _app("console"))
        assert created[0].argv == ["echo", "hi"]                    # NOT wrapped
        assert "creationflags" in created[0].kwargs
        assert "start_new_session" not in created[0].kwargs


def test_posix_stop_signals_process_group() -> None:
    calls: list[tuple[int, int]] = []
    with _patch(False, wrap_result=["ptyxis", "--", "echo", "hi"]) as created:
        real_getpgid, real_killpg = process_manager.os.getpgid, process_manager.os.killpg
        process_manager.os.getpgid = lambda pid: pid
        def fake_killpg(pgid, sig):
            calls.append((pgid, sig))
            created[0]._poll = 0            # process dies on the signal
        process_manager.os.killpg = fake_killpg
        try:
            pm = process_manager.ProcessManager()
            pm.launch(ROOT, _app("console"))
            assert pm.status("x") == "running"
            pm.stop("x")
        finally:
            process_manager.os.getpgid, process_manager.os.killpg = real_getpgid, real_killpg
    assert calls and calls[0] == (4242, signal.SIGTERM)
    assert pm.status("x") == "stopped"


def test_windows_stop_terminates() -> None:
    with _patch(True) as created:
        pm = process_manager.ProcessManager()
        pm.launch(ROOT, _app("console"))
        assert pm.status("x") == "running"
        pm.stop("x")
        assert created[0]._poll == 0
        assert pm.status("x") == "stopped"


def _run_standalone() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"process_manager: {len(tests)} passed")


if __name__ == "__main__":
    _run_standalone()
