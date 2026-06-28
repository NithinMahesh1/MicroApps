"""Headless smoke test for the QuizMe notes-folder dialog + empty state.

Mounts a minimal host app, drives QuizView's "no notes" empty state, then opens
NotesConfigScreen, adds a typed path, and Saves — asserting the config is
persisted and the screen dismisses ``True``. Skipped under pytest when Textual
is missing; runnable standalone (``python tests/test_notes_screen_smoke.py``).
"""
from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _scenario() -> None:
    from textual.app import App, ComposeResult
    from textual.widgets import Button, Input

    from ccdashboard import quiz
    from ccdashboard.tui.notes_config_screen import NotesConfigScreen
    from ccdashboard.tui.quiz_view import QuizView

    tmp = Path(tempfile.mkdtemp(prefix="ccd-notes-smoke-"))
    real_cfg, real_avail = quiz._config_path, quiz.is_available
    quiz._config_path = lambda: tmp / "config.json"
    quiz.is_available = lambda: True        # exercise the "no notes" path, not "no key"

    class HostApp(App):
        def compose(self) -> ComposeResult:
            yield QuizView(id="quiz-view")

    async def run() -> None:
        app = HostApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            qv = app.query_one(QuizView)

            # Empty quiz -> "no notes" empty state (card is None), notes button present.
            qv.load_quiz([], quiz.QuizState())
            await pilot.pause()
            assert qv._ccd_card is None
            assert app.query_one("#quiz-notes", Button) is not None

            # Open the notes dialog, add a typed path, Save.
            result: list = []
            screen = NotesConfigScreen(dirs=[])
            app.push_screen(screen, result.append)
            await pilot.pause()
            assert app.screen is screen
            screen.query_one("#notes-path", Input).value = str(tmp / "MyNotes")
            await pilot.pause()
            screen.query_one("#notes-add-path", Button).press()
            await pilot.pause()
            screen.query_one("#notes-save", Button).press()
            await pilot.pause()

            assert result and result[0] is True, result
            assert quiz.load_notes_dirs() == [tmp / "MyNotes"]

    try:
        asyncio.run(run())
    finally:
        quiz._config_path, quiz.is_available = real_cfg, real_avail
        shutil.rmtree(tmp, ignore_errors=True)


def test_notes_screen_smoke() -> None:
    if importlib.util.find_spec("textual") is None:
        import pytest

        pytest.skip("textual not installed")
    _scenario()


if __name__ == "__main__":
    _scenario()
    print("notes screen smoke OK")
