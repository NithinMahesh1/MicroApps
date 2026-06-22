"""QuizMe tab — one Claude-generated question per day, Claude-graded, SM-2 scheduled.

Matches the cyan/teal theme and the ``_ccd_`` conventions. Question generation
and grading run in ``@work(thread=True)`` workers; UI updates come back via
``self.app.call_from_thread(...)``. When ANTHROPIC_API_KEY is unset the engine
raises ``QuizUnavailable`` and this view shows a friendly "set the key" panel —
never a crash. Card extraction + scheduling work fully offline.
"""
from __future__ import annotations

from datetime import date

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Button, Static, TextArea

from ccdashboard import quiz


class QuizView(Vertical):
    """Status line · question · answer box · Submit · feedback.

    Custom instance attrs/methods are ``_ccd_`` prefixed to avoid colliding with
    Textual internals. Submit is bound to both ``ctrl+s`` and a Button — Enter
    inside a TextArea inserts a newline, and ``ctrl+enter`` is unreliable across
    terminals, so ``ctrl+s`` is the safe, discoverable choice (shows in Footer).
    """

    BINDINGS = [
        Binding("ctrl+s", "submit_answer", "Submit answer", show=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_cards: list[quiz.Card] = []
        self._ccd_state: quiz.QuizState = quiz.QuizState()
        self._ccd_card: quiz.Card | None = None
        self._ccd_question: str = ""
        self._ccd_busy: bool = False

    def compose(self) -> ComposeResult:
        yield Static("loading QuizMe…", id="quiz-status", classes="status")
        yield Static("", id="quiz-question", classes="quiz-question")
        yield TextArea("", id="quiz-answer", classes="quiz-answer")
        yield Button("Submit  (Ctrl+S)", id="quiz-submit", variant="primary")
        yield Static("", id="quiz-feedback", classes="quiz-feedback")

    # ---- engine hand-off from app._populate ----------------------------- #

    def load_quiz(self, cards: list[quiz.Card], state: quiz.QuizState) -> None:
        """Receive indexed cards + store (off-thread work already done)."""
        self._ccd_cards = cards
        self._ccd_state = state
        self._ccd_refresh_status()
        today = date.today()
        if not quiz.is_available():
            self._ccd_show_unavailable()
            return
        if quiz.answered_today(state.streak, today):
            self._ccd_show_done_for_today()
            return
        self._ccd_card = quiz.select_today(state, cards, today)
        if self._ccd_card is None:
            self.query_one("#quiz-question", Static).update(
                "No study notes found.\n\n"
                "Add Markdown notes under your Learning\\Codebase folder, then "
                "press Ctrl+R to refresh."
            )
            self._ccd_set_inputs_enabled(False)
            return
        self._ccd_generate_question()

    # ---- status / panels ------------------------------------------------ #

    def _ccd_refresh_status(self) -> None:
        s = self._ccd_state.streak
        today = date.today()
        due = quiz.due_count(self._ccd_state, self._ccd_cards, today)
        nxt = quiz.next_due_date(self._ccd_state, self._ccd_cards)
        parts = [
            f"streak {s.count} (best {s.longest})",
            f"{due} due",
            f"{len(self._ccd_cards)} cards",
        ]
        if nxt:
            parts.append(f"next due {nxt}")
        self.query_one("#quiz-status", Static).update("   ·   ".join(parts))

    def _ccd_show_unavailable(self) -> None:
        self.query_one("#quiz-question", Static).update(
            "Set ANTHROPIC_API_KEY to enable QuizMe.\n\n"
            "QuizMe uses Claude to generate a question from your study notes and "
            "grade your answer. Set the environment variable, then press Ctrl+R "
            "to refresh."
        )
        self.query_one("#quiz-feedback", Static).update("")
        self._ccd_set_inputs_enabled(False)

    def _ccd_show_done_for_today(self) -> None:
        nxt = quiz.next_due_date(self._ccd_state, self._ccd_cards)
        tail = f" Next review due {nxt}." if nxt else ""
        self.query_one("#quiz-question", Static).update(
            "You've done today's quiz. Come back tomorrow to keep your streak."
            f"{tail}"
        )
        self._ccd_set_inputs_enabled(False)

    def _ccd_set_inputs_enabled(self, enabled: bool) -> None:
        self.query_one("#quiz-answer", TextArea).disabled = not enabled
        self.query_one("#quiz-submit", Button).disabled = not enabled

    # ---- question generation (worker) ----------------------------------- #

    def _ccd_generate_question(self) -> None:
        if self._ccd_card is None:
            return
        self._ccd_busy = True
        self._ccd_set_inputs_enabled(False)
        self.query_one("#quiz-question", Static).update(
            f"Generating a question from “{self._ccd_card.title}”…"
        )
        self.query_one("#quiz-feedback", Static).update("")
        self._ccd_gen_worker(self._ccd_card)

    @work(thread=True, exclusive=True, group="quiz-gen")
    def _ccd_gen_worker(self, card: quiz.Card) -> None:
        try:
            question = quiz.gen_question(card)
        except quiz.QuizUnavailable as exc:
            self.app.call_from_thread(self._ccd_on_unavailable, str(exc))
            return
        except Exception as exc:  # noqa: BLE001 — surface API/network errors, never crash
            self.app.call_from_thread(self._ccd_on_error, f"Question failed: {exc}")
            return
        self.app.call_from_thread(self._ccd_on_question, question)

    def _ccd_on_question(self, question: str) -> None:
        self._ccd_busy = False
        self._ccd_question = question
        self.query_one("#quiz-question", Static).update(question)
        answer = self.query_one("#quiz-answer", TextArea)
        answer.text = ""
        self._ccd_set_inputs_enabled(True)
        self.query_one("#quiz-feedback", Static).update("")
        answer.focus()

    def _ccd_on_unavailable(self, _msg: str) -> None:
        self._ccd_busy = False
        self._ccd_show_unavailable()

    def _ccd_on_error(self, msg: str) -> None:
        self._ccd_busy = False
        node = self.query_one("#quiz-feedback", Static)
        node.add_class("feedback-error")
        node.update(msg)
        self._ccd_set_inputs_enabled(True)

    # ---- submit / grade (worker) ---------------------------------------- #

    def action_submit_answer(self) -> None:
        self._ccd_submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quiz-submit":
            self._ccd_submit()

    def _ccd_submit(self) -> None:
        if self._ccd_busy or self._ccd_card is None or not self._ccd_question:
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
        self._ccd_grade_worker(self._ccd_card, self._ccd_question, answer)

    @work(thread=True, exclusive=True, group="quiz-grade")
    def _ccd_grade_worker(self, card: quiz.Card, question: str, answer: str) -> None:
        try:
            grade = quiz.grade_answer(card, question, answer)
            new_state = quiz.apply_grade(self._ccd_state, card, grade.grade, date.today())
            quiz.save_state(new_state)
        except quiz.QuizUnavailable as exc:
            self.app.call_from_thread(self._ccd_on_unavailable, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._ccd_on_error, f"Grading failed: {exc}")
            return
        self.app.call_from_thread(self._ccd_on_graded, grade, new_state)

    def _ccd_on_graded(self, grade: quiz.QuizGrade, new_state: quiz.QuizState) -> None:
        self._ccd_state = new_state
        self._ccd_busy = False
        verdict = grade.verdict or ("correct" if grade.grade >= quiz.PASS_QUALITY else "incorrect")
        mark = "✓" if grade.grade >= quiz.PASS_QUALITY else "✗"
        node = self.query_one("#quiz-feedback", Static)
        node.remove_class("feedback-error")
        node.update(
            f"{mark}  [{verdict.upper()}]  grade {grade.grade}/5\n{grade.feedback}"
        )
        self._ccd_refresh_status()
        self._ccd_show_done_for_today()

    # ---- focus contract (app calls this on load + tab activation) ------- #

    def focus_search(self) -> None:
        """Focus the primary control (the answer box, else the submit button).

        The name mirrors the cross-view contract ``app.py`` depends on; for
        QuizMe the "primary control" is the answer box, falling back to the
        Submit button when the box is disabled (no-key / done-for-today).
        """
        answer = self.query_one("#quiz-answer", TextArea)
        if not answer.disabled:
            answer.focus()
        else:
            self.query_one("#quiz-submit", Button).focus()
