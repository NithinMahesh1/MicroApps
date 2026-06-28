"""Tests for the Linux resume terminal selection + per-emulator argv, and proof
that the WINDOWS resume path is unaffected by those changes (conversations.py).

Pure engine tests (no textual). Runnable under pytest or standalone
(``python tests/test_resume_terminal.py``).
"""
from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccdashboard import conversations as conv
from ccdashboard.conversations import Conversation


def _convo(session_id: str = "test-session-1", cwd: str = "/work dir") -> Conversation:
    return Conversation(
        session_id=session_id, cwd=cwd, git_branch="main", title="t",
        started_at="2026-06-28T00:00:00", last_at="2026-06-28T00:00:00",
        message_count=1, project_dir="/proj", file_path="/proj/x.jsonl",
    )


@contextmanager
def _which(available: set[str]):
    real = shutil.which
    conv.shutil.which = lambda name, *a, **k: (f"/fake/bin/{name}" if name in available else None)
    try:
        yield
    finally:
        conv.shutil.which = real


@contextmanager
def _os_name(value: str):
    real = os.name
    conv.os.name = value
    try:
        yield
    finally:
        conv.os.name = real


# ---- Linux terminal selection (the bug: ptyxis was missing) ---------------- #

def test_find_terminal_picks_ptyxis_when_only_one() -> None:
    with _which({"ptyxis"}):
        assert conv._find_terminal() == "/fake/bin/ptyxis"


def test_find_terminal_none_when_absent() -> None:
    with _which(set()):
        assert conv._find_terminal() is None


def test_find_terminal_respects_priority() -> None:
    with _which({"ptyxis", "x-terminal-emulator", "xterm"}):
        assert conv._find_terminal() == "/fake/bin/x-terminal-emulator"


# ---- per-emulator argv ----------------------------------------------------- #

def _argv(term: str) -> list[str]:
    return conv._linux_resume_argv(term, "/work dir", "/opt/claude", "abc-123")


def test_ptyxis_argv_is_standalone_after_separator() -> None:
    argv = _argv("/fake/bin/ptyxis")
    assert argv[0] == "/fake/bin/ptyxis"
    assert "--standalone" in argv and "--new-window" in argv
    assert argv[argv.index("--") + 1] == "bash"


def test_gnome_terminal_uses_double_dash() -> None:
    assert _argv("/fake/bin/gnome-terminal")[:3] == ["/fake/bin/gnome-terminal", "--", "bash"]


def test_kgx_uses_double_dash() -> None:
    assert _argv("/fake/bin/kgx")[:2] == ["/fake/bin/kgx", "--"]


def test_konsole_uses_dash_e() -> None:
    assert _argv("/fake/bin/konsole")[:2] == ["/fake/bin/konsole", "-e"]


def test_kitty_runs_command_directly() -> None:
    assert _argv("/fake/bin/kitty")[:2] == ["/fake/bin/kitty", "bash"]


def test_resume_command_shell_quotes_cwd() -> None:
    joined = " ".join(_argv("/fake/bin/xterm"))
    assert "cd '/work dir'" in joined                   # cwd quoted (it has a space)
    assert "/opt/claude --resume abc-123" in joined     # claude path + session id


# ---- WINDOWS path is unaffected by the Linux changes ----------------------- #

def test_windows_resume_plan_uses_powershell_not_argv() -> None:
    with _os_name("nt"):
        plan = conv.build_resume_plan(_convo())
    # Windows uses the PowerShell clipboard/admin path: a `command`, never a Linux
    # terminal argv/mode.
    assert "command" in plan
    assert "--resume test-session-1" in plan["command"]
    assert "argv" not in plan and "mode" not in plan


def test_windows_never_consults_linux_terminals() -> None:
    # With NO Linux terminal installed, the Windows path still succeeds (it never
    # calls _find_terminal) — so the ptyxis change cannot break Windows.
    with _os_name("nt"), _which(set()):
        plan = conv.build_resume_plan(_convo())
    assert "argv" not in plan and "--resume test-session-1" in plan["command"]


def _run_standalone() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"resume_terminal: {len(tests)} passed")


if __name__ == "__main__":
    _run_standalone()
