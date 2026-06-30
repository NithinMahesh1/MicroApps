"""Tests for QuizMe v2 engine (quiz.py): SM-2, grading, selection, state I/O.

Pure engine tests (no Textual, no network). Runnable under pytest or standalone
(``python tests/test_quiz.py``).
"""
from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccdashboard import quiz
from ccdashboard.models import (
    Attempt, CardState, FlashCard, QuizGrade, QuizState, Streak, Stats,
    EF_FLOOR, PASS_QUALITY,
)

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

TODAY = date(2026, 6, 24)


def _card(source: str, question: str, answer: str = "ans") -> FlashCard:
    return FlashCard.create(source=source, concept="test", question=question, answer=answer)


def _make_grade(g: int) -> QuizGrade:
    verdict = "correct" if g >= PASS_QUALITY else "incorrect"
    return QuizGrade(grade=g, verdict=verdict, feedback="ok")


@contextmanager
def _redirect_store(tmp_dir: Path):
    """Redirect quiz._store_path into *tmp_dir* for the duration of the block."""
    store_file = tmp_dir / "quizme.json"
    real = quiz._store_path
    quiz._store_path = lambda: store_file
    try:
        yield store_file
    finally:
        quiz._store_path = real


# --------------------------------------------------------------------------- #
# review — SM-2 math
# --------------------------------------------------------------------------- #

def test_review_pass_reps0_gives_interval1() -> None:
    cs = CardState()                            # reps=0, brand new
    new = quiz.review(cs, 4, TODAY)
    assert new.reps == 1
    assert new.interval == 1
    assert new.due == (TODAY + timedelta(days=1)).isoformat()


def test_review_pass_reps1_gives_interval6() -> None:
    cs = CardState(reps=1, interval=1, due=TODAY.isoformat())
    new = quiz.review(cs, 4, TODAY)
    assert new.reps == 2
    assert new.interval == 6


def test_review_pass_reps2_interval_uses_old_ease() -> None:
    old_ease = 2.5
    cs = CardState(reps=2, interval=6, ease=old_ease, due=TODAY.isoformat())
    new = quiz.review(cs, 4, TODAY)
    # interval must use OLD ease (2.5), not post-update ease
    assert new.interval == max(1, round(6 * old_ease))
    assert new.reps == 3


def test_review_fail_resets_reps_and_interval() -> None:
    cs = CardState(reps=3, interval=10, ease=2.5, due=TODAY.isoformat())
    new = quiz.review(cs, 2, TODAY)             # quality < PASS_QUALITY
    assert new.reps == 0
    assert new.interval == 1


def test_review_ease_floored_at_ef_floor() -> None:
    # Worst grade from a near-floor ease must not drop below EF_FLOOR
    cs = CardState(ease=EF_FLOOR + 0.05)
    new = quiz.review(cs, 0, TODAY)
    assert new.ease >= EF_FLOOR


def test_review_does_not_append_history() -> None:
    cs = CardState()
    new = quiz.review(cs, 5, TODAY)
    assert new.history == ()                    # history must stay untouched


def test_review_sets_last_grade() -> None:
    cs = CardState()
    new = quiz.review(cs, 3, TODAY)
    assert new.last_grade == 3


# --------------------------------------------------------------------------- #
# bump_streak
# --------------------------------------------------------------------------- #

def test_bump_streak_same_day_noop() -> None:
    s = Streak(count=3, longest=5, last_session=TODAY.isoformat())
    assert quiz.bump_streak(s, TODAY) is s      # exact same object returned


def test_bump_streak_consecutive_day_increments() -> None:
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    s = Streak(count=3, longest=5, last_session=yesterday)
    new = quiz.bump_streak(s, TODAY)
    assert new.count == 4
    assert new.longest == 5                     # 4 < 5, so longest unchanged


def test_bump_streak_gap_resets_to_1() -> None:
    two_days_ago = (TODAY - timedelta(days=2)).isoformat()
    s = Streak(count=3, longest=5, last_session=two_days_ago)
    new = quiz.bump_streak(s, TODAY)
    assert new.count == 1
    assert new.longest == 5                     # longest preserved on reset


def test_bump_streak_longest_updated_when_count_exceeds() -> None:
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    s = Streak(count=9, longest=9, last_session=yesterday)
    new = quiz.bump_streak(s, TODAY)
    assert new.count == 10
    assert new.longest == 10


def test_bump_streak_from_never_answered() -> None:
    s = Streak()                                # last_session == ""
    new = quiz.bump_streak(s, TODAY)
    assert new.count == 1
    assert new.longest == 1


# --------------------------------------------------------------------------- #
# Stats.record (exercised indirectly via apply_grade)
# --------------------------------------------------------------------------- #

def test_stats_totals_and_accuracy() -> None:
    st = QuizState()
    card = _card("a.md", "Q1?", "A1")
    st2 = quiz.apply_grade(st, card, _make_grade(5), "A1", TODAY)
    assert st2.stats.total_answered == 1
    assert st2.stats.total_correct == 1
    assert st2.stats.accuracy == 1.0

    card2 = _card("b.md", "Q2?", "A2")
    st3 = quiz.apply_grade(st2, card2, _make_grade(1), "wrong", TODAY)
    assert st3.stats.total_answered == 2
    assert st3.stats.total_correct == 1
    assert st3.stats.accuracy == 0.5


def test_stats_today_count_rolls_over_on_new_day() -> None:
    st = QuizState()
    g = _make_grade(5)
    st = quiz.apply_grade(st, _card("a.md", "Q1?"), g, "a", TODAY)
    st = quiz.apply_grade(st, _card("b.md", "Q2?"), g, "b", TODAY)
    assert st.stats.today_count == 2

    tomorrow = TODAY + timedelta(days=1)
    st = quiz.apply_grade(st, _card("c.md", "Q3?"), g, "c", tomorrow)
    assert st.stats.today_count == 1
    assert st.stats.today_date == tomorrow.isoformat()


def test_stats_best_day_tracked() -> None:
    st = QuizState()
    g = _make_grade(5)
    st = quiz.apply_grade(st, _card("a.md", "Q1?"), g, "a", TODAY)
    st = quiz.apply_grade(st, _card("b.md", "Q2?"), g, "b", TODAY)
    assert st.stats.best_day_count == 2
    assert st.stats.best_day_date == TODAY.isoformat()

    tomorrow = TODAY + timedelta(days=1)
    st = quiz.apply_grade(st, _card("c.md", "Q3?"), g, "c", tomorrow)
    # 1 answer tomorrow < 2 today → best_day stays
    assert st.stats.best_day_count == 2


# --------------------------------------------------------------------------- #
# apply_grade — full transactional advance
# --------------------------------------------------------------------------- #

def test_apply_grade_appends_one_attempt_with_full_fields() -> None:
    state = QuizState()
    card = _card("notes.md", "What is X?", "X is Y.")
    grade = QuizGrade(grade=4, verdict="correct", feedback="Good.")
    new_state = quiz.apply_grade(state, card, grade, "my answer", TODAY)

    cs = new_state.card_state(card.card_id)
    assert len(cs.history) == 1
    a = cs.history[0]
    assert a.question == "What is X?"
    assert a.answer == "my answer"
    assert a.grade == 4
    assert a.verdict == "correct"
    assert a.feedback == "Good."
    assert a.date == TODAY.isoformat()


def test_apply_grade_advances_sm2() -> None:
    state = QuizState()
    card = _card("notes.md", "Q?", "A.")
    new_state = quiz.apply_grade(state, card, _make_grade(5), "A.", TODAY)
    cs = new_state.card_state(card.card_id)
    assert cs.reps == 1
    assert cs.interval == 1                     # first review: reps was 0


def test_apply_grade_does_not_mutate_input_state() -> None:
    state = QuizState()
    card = _card("notes.md", "Q?", "A.")
    quiz.apply_grade(state, card, _make_grade(5), "A.", TODAY)
    # Original state must be completely unchanged (frozen + immutable convention)
    assert state.cards == {}
    assert state.streak.count == 0
    assert state.stats.total_answered == 0


def test_apply_grade_bumps_streak() -> None:
    state = QuizState()
    card = _card("notes.md", "Q?", "A.")
    new_state = quiz.apply_grade(state, card, _make_grade(4), "A.", TODAY)
    assert new_state.streak.count == 1
    assert new_state.streak.last_session == TODAY.isoformat()


def test_apply_grade_accumulates_attempts_across_calls() -> None:
    state = QuizState()
    card = _card("notes.md", "Q?", "A.")
    state = quiz.apply_grade(state, card, _make_grade(3), "first", TODAY)
    state = quiz.apply_grade(
        state, card, _make_grade(5), "second", TODAY + timedelta(days=1)
    )
    assert len(state.card_state(card.card_id).history) == 2


# --------------------------------------------------------------------------- #
# select_today and select_next_practice
# --------------------------------------------------------------------------- #

def test_select_today_prefers_overdue_over_new() -> None:
    overdue = _card("a.md", "Q overdue?")
    new_card = _card("b.md", "Q new?")
    state = QuizState(cards={
        overdue.card_id: CardState(
            due=(TODAY - timedelta(days=3)).isoformat(), reps=1, interval=3
        )
    })
    result = quiz.select_today(state, [overdue, new_card], TODAY)
    assert result is not None
    assert result.card_id == overdue.card_id


def test_select_today_prefers_new_over_upcoming() -> None:
    upcoming = _card("a.md", "Q upcoming?")
    new_card = _card("b.md", "Q new?")
    state = QuizState(cards={
        upcoming.card_id: CardState(
            due=(TODAY + timedelta(days=3)).isoformat(), reps=1, interval=3
        )
    })
    result = quiz.select_today(state, [upcoming, new_card], TODAY)
    assert result is not None
    assert result.card_id == new_card.card_id


def test_select_today_falls_back_to_upcoming() -> None:
    c = _card("a.md", "Q?")
    state = QuizState(cards={
        c.card_id: CardState(
            due=(TODAY + timedelta(days=2)).isoformat(), reps=1, interval=2
        )
    })
    result = quiz.select_today(state, [c], TODAY)
    assert result is not None
    assert result.card_id == c.card_id


def test_select_today_empty_returns_none() -> None:
    assert quiz.select_today(QuizState(), [], TODAY) is None


def test_select_next_practice_skips_excluded_id() -> None:
    c1 = _card("a.md", "Q1?")
    c2 = _card("b.md", "Q2?")
    state = QuizState()
    result = quiz.select_next_practice(
        state, [c1, c2], TODAY, exclude_ids=frozenset([c1.card_id])
    )
    assert result is not None
    assert result.card_id == c2.card_id


def test_select_next_practice_all_excluded_returns_none() -> None:
    c = _card("a.md", "Q?")
    result = quiz.select_next_practice(
        QuizState(), [c], TODAY, exclude_ids=frozenset([c.card_id])
    )
    assert result is None


def test_select_next_practice_prefers_overdue_then_new_then_upcoming() -> None:
    overdue = _card("a.md", "Q overdue?")
    new_card = _card("b.md", "Q new?")
    upcoming = _card("c.md", "Q upcoming?")
    state = QuizState(cards={
        overdue.card_id: CardState(
            due=(TODAY - timedelta(days=1)).isoformat(), reps=1, interval=1
        ),
        upcoming.card_id: CardState(
            due=(TODAY + timedelta(days=5)).isoformat(), reps=1, interval=5
        ),
    })
    # All three present — should pick overdue
    result = quiz.select_next_practice(state, [overdue, new_card, upcoming], TODAY)
    assert result is not None
    assert result.card_id == overdue.card_id

    # Exclude overdue — should pick new
    result2 = quiz.select_next_practice(
        state, [overdue, new_card, upcoming], TODAY,
        exclude_ids=frozenset([overdue.card_id])
    )
    assert result2 is not None
    assert result2.card_id == new_card.card_id

    # Exclude both overdue and new — should pick upcoming
    result3 = quiz.select_next_practice(
        state, [overdue, new_card, upcoming], TODAY,
        exclude_ids=frozenset([overdue.card_id, new_card.card_id])
    )
    assert result3 is not None
    assert result3.card_id == upcoming.card_id


# --------------------------------------------------------------------------- #
# due_count / next_due_date
# --------------------------------------------------------------------------- #

def test_due_count_counts_overdue_due_today_and_new() -> None:
    overdue = _card("a.md", "Q1?")
    due_today = _card("b.md", "Q2?")
    upcoming = _card("c.md", "Q3?")
    brand_new = _card("d.md", "Q4?")
    state = QuizState(cards={
        overdue.card_id: CardState(
            due=(TODAY - timedelta(days=2)).isoformat(), reps=1, interval=2
        ),
        due_today.card_id: CardState(due=TODAY.isoformat(), reps=1, interval=1),
        upcoming.card_id: CardState(
            due=(TODAY + timedelta(days=5)).isoformat(), reps=1, interval=5
        ),
    })
    count = quiz.due_count(state, [overdue, due_today, upcoming, brand_new], TODAY)
    assert count == 3                           # overdue + due_today + brand_new


def test_next_due_date_returns_soonest() -> None:
    c1 = _card("a.md", "Q1?")
    c2 = _card("b.md", "Q2?")
    state = QuizState(cards={
        c1.card_id: CardState(
            due=(TODAY + timedelta(days=3)).isoformat(), reps=1, interval=3
        ),
        c2.card_id: CardState(due=(TODAY + timedelta(days=1)).isoformat(), reps=1, interval=1),
    })
    result = quiz.next_due_date(state, [c1, c2])
    assert result == (TODAY + timedelta(days=1)).isoformat()


def test_next_due_date_no_scheduled_cards_returns_empty() -> None:
    c = _card("a.md", "Q?")
    assert quiz.next_due_date(QuizState(), [c]) == ""


# --------------------------------------------------------------------------- #
# grade_answer — monkeypatched (no network)
# --------------------------------------------------------------------------- #

def test_grade_answer_maps_to_quiz_grade(monkeypatch) -> None:
    parsed = SimpleNamespace(grade=4, verdict="correct", feedback="Well done.")

    class _FakeBlock:
        type = "text"
        parsed_output = parsed

    class _FakeResp:
        content = [_FakeBlock()]
        stop_reason = "end_turn"

    class _FakeMsgs:
        def parse(self, **kwargs):
            return _FakeResp()

    class _FakeClient:
        messages = _FakeMsgs()

    monkeypatch.setattr(quiz, "_client", lambda: _FakeClient())
    card = _card("notes.md", "What is X?", "X is Y.")
    result = quiz.grade_answer(card, "X is Y.")
    assert isinstance(result, QuizGrade)
    assert result.grade == 4
    assert result.verdict == "correct"
    assert result.feedback == "Well done."


def test_grade_answer_raises_quiz_unavailable_without_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    card = _card("notes.md", "Q?", "A.")
    try:
        quiz.grade_answer(card, "my answer")
    except quiz.QuizUnavailable:
        pass
    else:
        raise AssertionError("expected QuizUnavailable when ANTHROPIC_API_KEY is unset")


# --------------------------------------------------------------------------- #
# State round-trip + back-compat
# --------------------------------------------------------------------------- #

def test_save_load_state_roundtrip() -> None:
    attempt = Attempt.create("2026-06-24", "Q?", "A.", 5, "correct", "Good.")
    cs = CardState(
        ease=2.1, interval=10, reps=3, due="2026-07-04",
        last_grade=5, history=(attempt,),
    )
    card = _card("notes.md", "Q?", "A.")
    streak = Streak(count=5, longest=10, last_session="2026-06-24")
    stats = Stats(
        total_answered=20, total_correct=15,
        best_day_count=5, best_day_date="2026-06-20",
        today_count=2, today_date="2026-06-24",
    )
    original = QuizState(cards={card.card_id: cs}, streak=streak, stats=stats)

    with tempfile.TemporaryDirectory(prefix="ccd-quiz-rt-") as tmp:
        with _redirect_store(Path(tmp)):
            quiz.save_state(original)
            loaded = quiz.load_state()

    assert loaded.streak.count == 5
    assert loaded.streak.longest == 10
    assert loaded.stats.total_answered == 20
    assert loaded.stats.total_correct == 15
    loaded_cs = loaded.card_state(card.card_id)
    assert loaded_cs.ease == 2.1
    assert loaded_cs.interval == 10
    assert loaded_cs.reps == 3
    assert len(loaded_cs.history) == 1
    h = loaded_cs.history[0]
    assert h.grade == 5
    assert h.verdict == "correct"
    assert h.date == "2026-06-24"


def test_v1_backcompat_loads_without_error() -> None:
    """A v1-style dict (history=[[iso,grade]], no stats) must load cleanly."""
    v1_dict = {
        "version": 1,
        "streak": {"count": 3, "longest": 5, "last_session": "2026-06-20"},
        "cards": {
            "abc123": {
                "ease": 2.5,
                "interval": 6,
                "reps": 2,
                "due": "2026-06-25",
                "last_grade": 4,
                "history": [["2026-06-19", 4], ["2026-06-20", 4]],
            }
        },
    }
    state = QuizState.from_dict(v1_dict)
    assert state.streak.count == 3
    cs = state.cards["abc123"]
    assert len(cs.history) == 2
    assert cs.history[0].grade == 4
    assert cs.history[0].date == "2026-06-19"
    assert state.stats.total_answered == 0      # no stats block in v1 → zeroes


# --------------------------------------------------------------------------- #
# Standalone runner (no pytest needed)
# --------------------------------------------------------------------------- #

def _run_standalone() -> None:
    import inspect

    _orig_setattr = setattr  # built-in; captured before any shadowing in _Mp

    class _Mp:
        """Minimal monkeypatch stub for standalone test runner."""
        def __init__(self) -> None:
            self._attr: list[tuple] = []
            self._env: dict[str, str] = {}

        def setattr(self, target, name, val):  # noqa: A003
            self._attr.append((target, name, getattr(target, name)))
            _orig_setattr(target, name, val)

        def delenv(self, key: str, raising: bool = True) -> None:
            if key in os.environ:
                self._env[key] = os.environ.pop(key)
            elif raising:
                raise KeyError(key)

        def undo(self) -> None:
            for target, name, orig in reversed(self._attr):
                _orig_setattr(target, name, orig)
            for k, v in self._env.items():
                os.environ[k] = v

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        sig = inspect.signature(fn)
        mp = _Mp()
        try:
            if "monkeypatch" in sig.parameters:
                fn(monkeypatch=mp)
            else:
                fn()
        finally:
            mp.undo()
        print(f"  ok  {fn.__name__}")
    print(f"quiz: {len(tests)} passed")


if __name__ == "__main__":
    _run_standalone()
