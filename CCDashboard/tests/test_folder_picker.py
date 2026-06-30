"""Tests for the native folder-picker backends added in folder_picker.py.

Covers Windows (powershell), macOS (osascript), and platform fallback ordering.
No real dialogs are opened — shutil.which and subprocess.run are monkeypatched.

Runnable under pytest or standalone (``python tests/test_folder_picker.py``).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccdashboard import folder_picker


class _Proc:
    """Minimal subprocess.CompletedProcess stub."""

    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


@contextmanager
def _picker(available_set: set[str], run=None):
    """Monkeypatch folder_picker.shutil.which and folder_picker.subprocess.run.

    *available_set* controls which tool names appear to be on PATH.
    *run* is an optional callable that receives the argv list and returns a
    _Proc; when omitted, subprocess.run is not replaced.
    """
    real_which = folder_picker.shutil.which
    real_run = folder_picker.subprocess.run
    folder_picker.shutil.which = lambda name, *a, **k: (
        f"/fake/bin/{name}" if name in available_set else None
    )
    if run is not None:
        folder_picker.subprocess.run = lambda argv, **k: run(argv)
    try:
        yield
    finally:
        folder_picker.shutil.which = real_which
        folder_picker.subprocess.run = real_run


# ---- Windows backend (powershell / WinForms FolderBrowserDialog) ----------- #

def test_windows_picker_tool_is_powershell() -> None:
    with _picker({"powershell"}):
        assert folder_picker.picker_tool() == "powershell"
        assert folder_picker.available() is True


def test_windows_argv_has_sta_and_folderbrowserdialog() -> None:
    """argv must include -STA and reference FolderBrowserDialog."""
    captured: dict = {}

    def run(argv):
        captured["argv"] = argv
        return _Proc(0, "C:\\Users\\x\\Notes\n")

    with _picker({"powershell"}, run=run):
        folder_picker.pick_directories(Path("C:/start"))

    argv = captured["argv"]
    assert argv[0] == "powershell"
    assert "-STA" in argv
    assert "FolderBrowserDialog" in " ".join(argv)


def test_windows_parses_single_path() -> None:
    with _picker({"powershell"}, run=lambda argv: _Proc(0, "C:\\Users\\x\\Notes\n")):
        result = folder_picker.pick_directories(Path("C:/start"))
    assert result == [Path("C:/Users/x/Notes")]


def test_windows_cancel_returns_empty() -> None:
    with _picker({"powershell"}, run=lambda argv: _Proc(1, "")):
        assert folder_picker.pick_directories(Path("C:/start")) == []


# ---- macOS backend (osascript / AppleScript choose folder) ----------------- #

def test_macos_picker_tool_is_osascript() -> None:
    with _picker({"osascript"}):
        assert folder_picker.picker_tool() == "osascript"
        assert folder_picker.available() is True


def test_macos_argv_invokes_osascript_with_choose_folder() -> None:
    captured: dict = {}

    def run(argv):
        captured["argv"] = argv
        return _Proc(0, "/Users/x/Notes\n")

    with _picker({"osascript"}, run=run):
        folder_picker.pick_directories(Path("/Users/x"))

    argv = captured["argv"]
    assert argv[0] == "osascript"
    assert "choose folder" in " ".join(argv)


def test_macos_parses_multiple_paths() -> None:
    with _picker({"osascript"}, run=lambda argv: _Proc(0, "/Users/x/Notes\n/Users/x/More\n")):
        result = folder_picker.pick_directories(Path("/Users/x"))
    assert result == [Path("/Users/x/Notes"), Path("/Users/x/More")]


def test_macos_cancel_returns_empty() -> None:
    with _picker({"osascript"}, run=lambda argv: _Proc(1, "")):
        assert folder_picker.pick_directories() == []


# ---- platform fallback ordering -------------------------------------------- #

def test_windows_prefers_powershell_over_zenity() -> None:
    """When powershell and zenity are both present, powershell wins on Windows."""
    with _picker({"powershell", "zenity"}):
        assert folder_picker.picker_tool() == "powershell"


def test_only_zenity_falls_through_when_powershell_absent() -> None:
    """Without powershell/pwsh, discovery falls through to zenity on any platform.

    This is the key back-compat guarantee: the older tests in test_quiz_config.py
    expose only zenity, and picker_tool() must still return "zenity".
    """
    with _picker({"zenity"}):
        assert folder_picker.picker_tool() == "zenity"


# ---- unavailable ----------------------------------------------------------- #

def test_available_false_when_no_tools() -> None:
    with _picker(set()):
        assert folder_picker.available() is False


def test_pick_directories_raises_picker_unavailable() -> None:
    with _picker(set()):
        try:
            folder_picker.pick_directories()
        except folder_picker.PickerUnavailable:
            pass
        else:
            raise AssertionError("expected PickerUnavailable")


def _run_standalone() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"folder_picker: {len(tests)} passed")


if __name__ == "__main__":
    _run_standalone()
