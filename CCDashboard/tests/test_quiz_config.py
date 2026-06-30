"""Tests for QuizMe notes-folder config (quiz.py) + the native folder picker.

Pure engine tests (no textual). Runnable under pytest or standalone
(``python tests/test_quiz_config.py``).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccdashboard import folder_picker, quiz


@contextmanager
def _workspace():
    """Temp dir; redirect quiz's config + default notes dir into it; clear env."""
    tmp = Path(tempfile.mkdtemp(prefix="ccd-quiz-test-"))
    real_cfg, real_default = quiz._config_path, quiz._default_notes_dir
    real_env = os.environ.pop(quiz._NOTES_DIR_ENV, None)
    quiz._config_path = lambda: tmp / "config.json"
    quiz._default_notes_dir = lambda: tmp / "default-notes"
    try:
        yield tmp
    finally:
        quiz._config_path, quiz._default_notes_dir = real_cfg, real_default
        os.environ.pop(quiz._NOTES_DIR_ENV, None)
        if real_env is not None:
            os.environ[quiz._NOTES_DIR_ENV] = real_env
        shutil.rmtree(tmp, ignore_errors=True)


# ---- notes-dir resolution -------------------------------------------------- #

def test_default_when_no_config_or_env() -> None:
    with _workspace() as tmp:
        assert quiz.load_notes_dirs() == [tmp / "default-notes"]


def test_env_var_used_when_no_config() -> None:
    with _workspace() as tmp:
        a, b = tmp / "a", tmp / "b"
        os.environ[quiz._NOTES_DIR_ENV] = f"{a}{os.pathsep}{b}"
        assert quiz.load_notes_dirs() == [a, b]


def test_config_beats_env() -> None:
    with _workspace() as tmp:
        os.environ[quiz._NOTES_DIR_ENV] = str(tmp / "env-dir")
        quiz.save_notes_dirs([tmp / "cfg1", tmp / "cfg2"])
        assert quiz.load_notes_dirs() == [tmp / "cfg1", tmp / "cfg2"]


def test_save_roundtrip_and_dedup() -> None:
    with _workspace() as tmp:
        saved = quiz.save_notes_dirs([tmp / "x", tmp / "x", tmp / "y"])
        assert saved == [tmp / "x", tmp / "y"]              # de-duplicated
        assert quiz.load_notes_dirs() == [tmp / "x", tmp / "y"]


def test_save_empty_clears_back_to_default() -> None:
    with _workspace() as tmp:
        quiz.save_notes_dirs([tmp / "x"])
        quiz.save_notes_dirs([])                            # clear the setting
        assert quiz.load_notes_dirs() == [tmp / "default-notes"]


def test_expand_dir_user_and_env() -> None:
    os.environ["CCD_TEST_VAR"] = "/var/ccd-test"
    try:
        assert quiz.expand_dir("$CCD_TEST_VAR/notes") == Path("/var/ccd-test/notes")
        assert quiz.expand_dir("~/notes") == Path.home() / "notes"
    finally:
        os.environ.pop("CCD_TEST_VAR", None)


# ---- native folder picker -------------------------------------------------- #

class _Proc:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


@contextmanager
def _picker(available: set[str], run=None):
    real_which, real_run = shutil.which, subprocess.run
    folder_picker.shutil.which = lambda name, *a, **k: (
        f"/fake/bin/{name}" if name in available else None
    )
    if run is not None:
        folder_picker.subprocess.run = lambda argv, **k: run(argv)
    try:
        yield
    finally:
        folder_picker.shutil.which = real_which
        folder_picker.subprocess.run = real_run


def test_picker_prefers_zenity() -> None:
    with _picker({"zenity", "kdialog"}):
        assert folder_picker.picker_tool() == "zenity"
        assert folder_picker.available() is True


def test_picker_unavailable_raises() -> None:
    with _picker(set()):
        assert folder_picker.available() is False
        try:
            folder_picker.pick_directories()
        except folder_picker.PickerUnavailable:
            pass
        else:
            raise AssertionError("expected PickerUnavailable")


def test_pick_directories_parses_multiselect() -> None:
    captured: dict[str, list[str]] = {}

    def run(argv):
        captured["argv"] = argv
        return _Proc(0, "/picked/one\n/picked/two two\n")

    with _picker({"zenity"}, run=run):
        dirs = folder_picker.pick_directories(Path("/start"))
    assert dirs == [Path("/picked/one"), Path("/picked/two two")]
    argv = captured["argv"]
    assert argv[0] == "zenity"
    assert "--directory" in argv and "--multiple" in argv


def test_pick_directories_cancel_returns_empty() -> None:
    with _picker({"zenity"}, run=lambda argv: _Proc(1, "")):
        assert folder_picker.pick_directories() == []


def _run_standalone() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"quiz_config: {len(tests)} passed")


if __name__ == "__main__":
    _run_standalone()
