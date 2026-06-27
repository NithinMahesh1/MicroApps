"""Tests for ``microapps_launcher.terminal`` (new-terminal-window wrapping).

Pure engine test (no textual). Runnable under pytest or standalone
(``python tests/test_terminal.py``).
"""
from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microapps_launcher import terminal


@contextmanager
def _patch(available: set[str], term: str | None = None, macos: bool = False):
    """Patch terminal detection: only *available* names resolve on PATH,
    optionally with a ``$TERMINAL`` override and a forced ``is_macos`` value."""
    real_which, real_is_macos = shutil.which, terminal.is_macos
    real_term = os.environ.get("TERMINAL")
    shutil.which = lambda name, *a, **k: (f"/fake/bin/{name}" if name in available else None)
    terminal.is_macos = lambda: macos
    if term is None:
        os.environ.pop("TERMINAL", None)
    else:
        os.environ["TERMINAL"] = term
    try:
        yield
    finally:
        shutil.which, terminal.is_macos = real_which, real_is_macos
        if real_term is None:
            os.environ.pop("TERMINAL", None)
        else:
            os.environ["TERMINAL"] = real_term


def test_ptyxis_preferred_and_argv_after_separator() -> None:
    with _patch({"ptyxis", "gnome-terminal", "xterm"}):
        assert terminal.chosen_terminal() == "ptyxis"
        cmd = terminal.wrap("/work/dir", ["python", "app.py"])
    assert cmd[0] == "ptyxis"
    assert "--standalone" in cmd                       # trackable (own process)
    assert "--working-directory=/work/dir" in cmd
    assert cmd[cmd.index("--") + 1:] == ["python", "app.py"]  # argv untouched


def test_priority_falls_through_to_xterm() -> None:
    with _patch({"xterm"}):
        assert terminal.chosen_terminal() == "xterm"
        assert terminal.wrap("/w", ["a", "b"]) == ["xterm", "-e", "a", "b"]


def test_gnome_terminal_is_wrapped_with_wait() -> None:
    with _patch({"gnome-terminal", "xterm"}):
        cmd = terminal.wrap("/w", ["x"])
    assert cmd[0] == "gnome-terminal" and "--wait" in cmd  # keeps client trackable


def test_konsole_uses_nofork() -> None:
    with _patch({"konsole"}):
        cmd = terminal.wrap("/w", ["x"])
    assert cmd[0] == "konsole" and "--nofork" in cmd


def test_env_override_beats_default_priority() -> None:
    with _patch({"konsole", "ptyxis"}, term="konsole"):
        assert terminal.chosen_terminal() == "konsole"
        cmd = terminal.wrap("/w", ["x", "y"])
    assert cmd[0] == "konsole"


def test_env_override_unknown_uses_generic_dash_e() -> None:
    with _patch({"myterm"}, term="myterm"):
        assert terminal.wrap("/w", ["x", "y"]) == ["myterm", "-e", "x", "y"]


def test_no_terminal_raises_oserror() -> None:
    with _patch(set()):
        assert terminal.chosen_terminal() is None
        try:
            terminal.wrap("/w", ["x"])
        except terminal.TerminalNotFound as exc:
            assert isinstance(exc, OSError)  # caught by existing launch handling
        else:
            raise AssertionError("expected TerminalNotFound")


def test_macos_uses_osascript() -> None:
    with _patch({"osascript"}, macos=True):
        assert terminal.chosen_terminal() == "Terminal.app"
        cmd = terminal.wrap("/some dir", ["python", "app.py"])
    assert cmd[:2] == ["osascript", "-e"]
    assert "Terminal" in cmd[2] and "app.py" in cmd[2]


def _run_standalone() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"terminal: {len(tests)} passed")


if __name__ == "__main__":
    _run_standalone()
