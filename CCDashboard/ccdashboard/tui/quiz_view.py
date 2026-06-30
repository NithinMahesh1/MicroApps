"""QuizMe tab — flash-card deck quiz (v2): pre-generated cards, SM-2 scheduled, Claude-graded.

v2 no longer generates questions live. Flash cards come from pre-generated decks
(``flashcards.py``). A background build runs on app open; cards already on disk
are quizzable immediately. Free practice continues after the daily card, unlimited.

_ccd_ prefix for all instance attrs/methods; @work(thread=True) + call_from_thread
for anything that touches the network or disk.
"""
from __future__ import annotations

import datetime

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, ProgressBar, Static, TextArea

from ccdashboard import quiz
from ccdashboard.models import PASS_QUALITY, FlashCard, QuizGrade, QuizState

# flashcards.py is delivered by a concurrent agent; guard the import so this
# module is importable even before that module exists on disk.
try:
    from ccdashboard import flashcards as _flashcards
except ImportError:  # pragma: no cover
    _flashcards = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# CardHistoryModal
# --------------------------------------------------------------------------- #


class CardHistoryModal(ModalScreen):
    """Modal showing the graded-attempt history for the current card (Esc closes)."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, card: FlashCard, state: QuizState) -> None:
        super().__init__()
        self._ccd_card = card
        self._ccd_state = state

    def compose(self) -> ComposeResult:
        with Vertical(id="history-dialog"):
            yield Static(self._ccd_render(), id="history-content")
            yield Button("Close  (Esc)", id="history-close")

    def _ccd_render(self) -> str:
        cs = self._ccd_state.card_state(self._ccd_card.card_id)
        lines: list[str] = [f"[b]{self._ccd_card.title}[/b]", ""]
        if not cs.history:
            lines.append("No attempts yet for this card.")
        else:
            # Most recent first — reversed() works on tuples
            for att in reversed(cs.history):
                # att is an Attempt (v2) with .date .grade .verdict .answer .feedback
                grade_val = getattr(att, "grade", 0)
                mark = "✓" if grade_val >= PASS_QUALITY else "✗"
                verdict = getattr(att, "verdict", "") or (
                    "correct" if grade_val >= PASS_QUALITY else "incorrect"
                )
                raw_ans = getattr(att, "answer", "")
                ans = (raw_ans[:60] + "…") if len(raw_ans) > 60 else raw_ans
                raw_fb = getattr(att, "feedback", "")
                lines.append(
                    f"{getattr(att, 'date', '')}  {mark} "
                    f"[{verdict.upper()}] grade {grade_val}/5"
                )
                if ans:
                    lines.append(f"  Your answer: {ans}")
                if raw_fb:
                    lines.append(f"  Feedback: {raw_fb}")
                lines.append("")
        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # noqa: ARG002
        self.dismiss()


# --------------------------------------------------------------------------- #
# GradeResultModal
# --------------------------------------------------------------------------- #


class GradeResultModal(ModalScreen[bool]):
    """The graded answer shown as an overlay (like the Notes/History dialogs).

    Dismisses ``True`` when the user chooses "Next card", else ``False``
    (Close / Esc) so they stay on the just-graded card.
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("ctrl+n", "next", "Next card"),
    ]

    def __init__(self, grade: QuizGrade, card_title: str) -> None:
        super().__init__()
        self._ccd_grade = grade
        self._ccd_title = card_title

    def compose(self) -> ComposeResult:
        with Vertical(id="grade-dialog"):
            yield Static(self._ccd_render(), id="grade-content")
            with Horizontal(id="grade-actions"):
                yield Button("Next card  (Ctrl+N)", id="grade-next", variant="primary")
                yield Button("Close  (Esc)", id="grade-close")

    def _ccd_render(self) -> str:
        from rich.markup import escape

        g = self._ccd_grade
        passed = g.grade >= PASS_QUALITY
        mark = "✓" if passed else "✗"
        verdict = (g.verdict or ("correct" if passed else "incorrect")).upper()
        colour = "#19f0d4" if passed else "#ff7a7a"
        lines: list[str] = []
        if self._ccd_title:
            lines += [f"[b]{escape(self._ccd_title)}[/b]", ""]
        lines.append(f"[{colour}]{mark}  {escape(verdict)}  ·  grade {g.grade}/5[/]")
        if g.feedback:
            lines += ["", escape(g.feedback)]
        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "grade-next")

    def action_close(self) -> None:
        self.dismiss(False)

    def action_next(self) -> None:
        self.dismiss(True)


# --------------------------------------------------------------------------- #
# QuizView
# --------------------------------------------------------------------------- #


class QuizView(Vertical):
    """Status · card · answer · Submit · Next · feedback.

    Custom instance attrs/methods are ``_ccd_`` prefixed.
    Ctrl+S = submit  |  Ctrl+N = next card  |  Ctrl+H = history
    Ctrl+B = build deck  |  Ctrl+O = notes folders
    """

    BINDINGS = [
        Binding("ctrl+s", "submit_answer", "Submit", show=True),
        Binding("ctrl+n", "next_card", "Next card", show=True),
        Binding("ctrl+h", "show_history", "History", show=True),
        Binding("ctrl+b", "build_deck", "Build deck", show=True),
        Binding("ctrl+o", "choose_notes", "Notes Folders", show=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_cards: list[FlashCard] = []
        self._ccd_state: QuizState = QuizState()
        self._ccd_card: FlashCard | None = None
        self._ccd_busy: bool = False
        self._ccd_seen: set[str] = set()

    # ---- compose ---------------------------------------------------------- #

    def compose(self) -> ComposeResult:
        yield Static("loading QuizMe…", id="quiz-status", classes="status")
        with Horizontal(id="quiz-build-row", classes="quiz-build-row"):
            yield Static("", id="quiz-build-label", classes="quiz-build-label")
            yield ProgressBar(id="quiz-build-bar", total=100, show_eta=False)
        yield Static("", id="quiz-question", classes="quiz-question")
        yield TextArea("", id="quiz-answer", classes="quiz-answer")
        with Horizontal(id="quiz-actions", classes="quiz-actions"):
            yield Button("Submit  (Ctrl+S)", id="quiz-submit", variant="primary")
            yield Button("Notes Folders…  (Ctrl+O)", id="quiz-notes")
            yield Button("Next card  (Ctrl+N)", id="quiz-next", variant="default")
        yield Static("", id="quiz-feedback", classes="quiz-feedback")

    # ---- engine hand-off from app._populate ------------------------------ #

    def load_quiz(self, cards: list[FlashCard], state: QuizState) -> None:
        """Receive pre-loaded flash cards + quiz state (called on the UI thread).

        Post-conditions the smoke test depends on:
        - ``load_quiz([], QuizState())`` leaves ``self._ccd_card is None``.
        - ``#quiz-notes`` Button is always present in compose.
        """
        self._ccd_cards = list(cards)
        self._ccd_state = state
        self._ccd_seen = set()
        self._ccd_card = None
        self._ccd_refresh_status()

        if not quiz.is_available():
            self._ccd_show_unavailable()
            return

        today = datetime.date.today()
        card = quiz.select_today(state, cards, today)
        if card is None:
            self._ccd_show_no_cards()
            return

        self._ccd_present_card(card)

    # ---- card presentation ------------------------------------------------ #

    def _ccd_present_card(self, card: FlashCard) -> None:
        """Display the card's stored question directly — no live generation."""
        self._ccd_card = card
        try:
            self.query_one("#quiz-question", Static).update(
                f"[b]{card.title}[/b]\n\n{card.question}"
            )
            answer_box = self.query_one("#quiz-answer", TextArea)
            answer_box.text = ""
            fb = self.query_one("#quiz-feedback", Static)
            fb.update("")
            fb.remove_class("feedback-error")
            self._ccd_set_inputs_enabled(True)
            self._ccd_set_display("#quiz-next", False)
            answer_box.focus()
        except Exception:  # noqa: BLE001 — widget may not be mounted yet
            pass

    # ---- status line ------------------------------------------------------ #

    def _ccd_refresh_status(self) -> None:
        s = self._ccd_state.streak
        # stats is a v2 field; guard with getattr for v1-state compat in smoke tests
        st = getattr(self._ccd_state, "stats", None)
        today = datetime.date.today()
        try:
            due = quiz.due_count(self._ccd_state, self._ccd_cards, today)
        except Exception:  # noqa: BLE001
            due = 0
        answered = st.total_answered if st else 0
        acc = f"{st.accuracy:.0%}" if (st and st.total_answered) else "—"
        parts = [
            f"streak {s.count} (best {s.longest})",
            f"{due} due",
            f"{answered} answered",
            f"{acc} accuracy",
            f"{len(self._ccd_cards)} cards",
        ]
        try:
            self.query_one("#quiz-status", Static).update("   ·   ".join(parts))
        except Exception:  # noqa: BLE001
            pass

    # ---- info panels ------------------------------------------------------ #

    def _ccd_show_unavailable(self) -> None:
        try:
            self.query_one("#quiz-question", Static).update(
                "Set ANTHROPIC_API_KEY to enable QuizMe.\n\n"
                "QuizMe uses Claude to grade your answers. Set the environment "
                "variable, then press Ctrl+R to refresh."
            )
            self.query_one("#quiz-feedback", Static).update("")
            self._ccd_set_inputs_enabled(False)
            self._ccd_set_display("#quiz-next", False)
        except Exception:  # noqa: BLE001
            pass

    def _ccd_show_no_cards(self) -> None:
        """No cards available yet — deck still building or no notes configured."""
        try:
            dirs = quiz.load_notes_dirs()
            where = "\n".join(f"  • {d}" for d in dirs) or "  • (none configured)"
            self.query_one("#quiz-question", Static).update(
                "No flash cards yet.\n\n"
                "Decks may still be generating, or no notes were found in:\n"
                f"{where}\n\n"
                'Click "Notes folders..." (Ctrl+O) to configure your .md notes '
                "folders. Cards already on disk appear immediately; "
                "new ones arrive as the background build finishes."
            )
            self._ccd_set_inputs_enabled(False)
            self._ccd_set_display("#quiz-next", False)
        except Exception:  # noqa: BLE001
            pass

    # ---- helpers ---------------------------------------------------------- #

    def _ccd_set_inputs_enabled(self, enabled: bool) -> None:
        try:
            self.query_one("#quiz-answer", TextArea).disabled = not enabled
            self.query_one("#quiz-submit", Button).disabled = not enabled
        except Exception:  # noqa: BLE001
            pass

    def _ccd_set_display(self, selector: str, visible: bool) -> None:
        try:
            self.query_one(selector).display = visible
        except Exception:  # noqa: BLE001
            pass

    # ---- submit / grade (worker) ----------------------------------------- #

    def action_submit_answer(self) -> None:
        self._ccd_submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "quiz-submit":
            self._ccd_submit()
        elif bid == "quiz-next":
            self._ccd_next_card()
        elif bid == "quiz-notes":
            self._ccd_open_notes_config()

    def _ccd_submit(self) -> None:
        if self._ccd_busy or self._ccd_card is None:
            return
        feedback = self.query_one("#quiz-feedback", Static)
        answer = self.query_one("#quiz-answer", TextArea).text.strip()
        if not answer:
            feedback.remove_class("feedback-error")
            feedback.update("Type an answer first.")
            return
        self._ccd_busy = True
        self._ccd_set_inputs_enabled(False)
        feedback.remove_class("feedback-error")
        feedback.update("Grading…")
        self._ccd_grade_worker(self._ccd_card, answer)

    @work(thread=True, exclusive=True, group="quiz-grade")
    def _ccd_grade_worker(self, card: FlashCard, answer: str) -> None:
        try:
            # v2 API: grade_answer(card, answer) — question is on the card itself
            grade = quiz.grade_answer(card, answer)
            today = datetime.date.today()
            # v2 API: apply_grade(state, card, grade_obj, answer, today)
            new_state = quiz.apply_grade(self._ccd_state, card, grade, answer, today)
            quiz.save_state(new_state)
        except quiz.QuizUnavailable as exc:
            self.app.call_from_thread(self._ccd_on_unavailable, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._ccd_on_error, f"Grading failed: {exc}")
            return
        self.app.call_from_thread(self._ccd_on_graded, grade, new_state, card.card_id)

    def _ccd_on_graded(self, grade, new_state: QuizState, card_id: str) -> None:
        self._ccd_state = new_state
        self._ccd_busy = False
        self._ccd_seen.add(card_id)
        self._ccd_refresh_status()
        self._ccd_set_display("#quiz-next", True)
        # The graded result is shown in an overlay modal, not inline — clear the
        # transient "Grading…" text behind it.
        try:
            fb = self.query_one("#quiz-feedback", Static)
            fb.remove_class("feedback-error")
            fb.update("")
        except Exception:  # noqa: BLE001
            pass
        title = self._ccd_card.title if self._ccd_card else ""
        self.app.push_screen(GradeResultModal(grade, title), self._ccd_after_grade)

    def _ccd_after_grade(self, go_next: bool | None) -> None:
        """Grade modal closed — advance only if the user chose "Next card"."""
        if go_next:
            self._ccd_next_card()

    def _ccd_on_unavailable(self, _msg: str) -> None:
        self._ccd_busy = False
        self._ccd_show_unavailable()

    def _ccd_on_error(self, msg: str) -> None:
        self._ccd_busy = False
        try:
            node = self.query_one("#quiz-feedback", Static)
            node.add_class("feedback-error")
            node.update(msg)
            self._ccd_set_inputs_enabled(True)
        except Exception:  # noqa: BLE001
            pass

    # ---- next card (free practice) --------------------------------------- #

    def action_next_card(self) -> None:
        self._ccd_next_card()

    def _ccd_next_card(self) -> None:
        if self._ccd_busy:
            return
        today = datetime.date.today()
        card = quiz.select_next_practice(
            self._ccd_state,
            self._ccd_cards,
            today,
            exclude_ids=frozenset(self._ccd_seen),
        )
        if card is None:
            # All cards seen — reset and start another round
            self._ccd_seen.clear()
            card = quiz.select_next_practice(
                self._ccd_state,
                self._ccd_cards,
                today,
                exclude_ids=frozenset(),
            )
        if card is None:
            try:
                self.query_one("#quiz-question", Static).update(
                    "You've reviewed everything available — great work!\n\n"
                    "Come back tomorrow for newly-due cards."
                )
                self.query_one("#quiz-feedback", Static).update("")
                self._ccd_set_inputs_enabled(False)
                self._ccd_set_display("#quiz-next", False)
            except Exception:  # noqa: BLE001
                pass
            return
        self._ccd_present_card(card)

    # ---- history modal --------------------------------------------------- #

    def action_show_history(self) -> None:
        if self._ccd_card is None:
            self.notify("No card is currently shown.", severity="warning")
            return
        self.app.push_screen(CardHistoryModal(self._ccd_card, self._ccd_state))

    # ---- build progress (called by app.py via call_from_thread) ---------- #

    def set_build_progress(self, done: int, total: int, source: str) -> None:
        """Show/advance the build progress bar (marshalled from the app build worker)."""
        try:
            self._ccd_set_display("#quiz-build-row", True)
            self.query_one("#quiz-build-label", Static).update(
                f"Generating flash cards… {done}/{total}  [{source[:30]}]"
            )
            bar = self.query_one("#quiz-build-bar", ProgressBar)
            if total > 0:
                bar.update(total=total, progress=done)
        except Exception:  # noqa: BLE001 — not yet mounted or progress bar API
            pass

    def on_build_done(self, result) -> None:
        """Called when the background build finishes (result: flashcards.BuildResult)."""
        try:
            self._ccd_set_display("#quiz-build-row", False)
            if getattr(result, "generated", 0) > 0 and _flashcards is not None:
                new_cards = _flashcards.load_decks()
                self._ccd_cards = list(new_cards)
                self._ccd_refresh_status()
                if self._ccd_card is None and quiz.is_available():
                    card = quiz.select_today(
                        self._ccd_state, new_cards, datetime.date.today()
                    )
                    if card is not None:
                        self._ccd_present_card(card)
        except Exception:  # noqa: BLE001
            pass

    # ---- manual rebuild (ctrl+b) ----------------------------------------- #

    def action_build_deck(self) -> None:
        if _flashcards is None or not _flashcards.is_available():
            self.notify("Set ANTHROPIC_API_KEY to build decks.", severity="warning")
            return
        self._ccd_run_build()

    @work(thread=True, exclusive=True, group="quiz-build")
    def _ccd_run_build(self) -> None:
        if _flashcards is None:
            return

        def _cb(done: int, total: int, source: str) -> None:
            self.app.call_from_thread(self.set_build_progress, done, total, source)

        try:
            result = _flashcards.build_decks(quiz.load_notes_dirs(), progress_cb=_cb)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.app.notify,
                f"Deck build failed: {exc}",
                severity="error",
                timeout=8,
            )
            return
        self.app.call_from_thread(self.on_build_done, result)

    # ---- notes-folder configuration ------------------------------------- #

    def action_choose_notes(self) -> None:
        self._ccd_open_notes_config()

    def _ccd_open_notes_config(self) -> None:
        from ccdashboard.tui.notes_config_screen import NotesConfigScreen

        self.app.push_screen(NotesConfigScreen(), self._ccd_on_notes_saved)

    def _ccd_on_notes_saved(self, changed: bool | None) -> None:
        if changed:
            try:
                self.query_one("#quiz-question", Static).update("Reloading…")
            except Exception:  # noqa: BLE001
                pass
            self._ccd_reload_cards()
            # Kick a build for any new/changed notes (runs alongside the reload)
            if _flashcards is not None and _flashcards.is_available():
                self._ccd_run_build()

    @work(thread=True, exclusive=True, group="quiz-reload")
    def _ccd_reload_cards(self) -> None:
        cards = _flashcards.load_decks() if _flashcards is not None else []
        state = quiz.load_state()
        self.app.call_from_thread(self.load_quiz, cards, state)

    # ---- focus contract -------------------------------------------------- #

    def focus_search(self) -> None:
        """Focus the primary control (answer box when enabled, else Submit button).

        The name mirrors the cross-view contract app.py depends on.
        """
        try:
            answer = self.query_one("#quiz-answer", TextArea)
            if not answer.disabled:
                answer.focus()
            else:
                self.query_one("#quiz-submit", Button).focus()
        except Exception:  # noqa: BLE001
            pass
