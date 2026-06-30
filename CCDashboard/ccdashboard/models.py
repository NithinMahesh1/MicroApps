"""
models.py — shared, immutable data records for QuizMe v2 (generated flash-card decks).

Pure stdlib: **no I/O and no Claude calls**, so every other QuizMe module can import
these types without an import cycle:
  * ``flashcards.py`` — generates cards (Claude/Sonnet) + reads/writes Markdown decks.
  * ``quiz.py``       — SM-2 scheduling, streak, stats, grading (Claude/Opus), selection.
  * the TUI views     — render/operate over the same records.

All records are frozen + slotted and round-trip through plain dicts/JSON.

Model split (mirrors CCDashboard's UI-agnostic engine):
  * FlashCard  — one generated question/answer card (the unit of study).
  * Attempt    — one graded answer to a card (date + question + your answer + grade).
  * CardState  — SM-2 schedule for a card + its full Attempt history.
  * Streak     — daily-quiz streak.
  * Stats      — lifetime "high score" totals (answered / correct / best single day).
  * QuizState  — the whole persisted store: per-card states + streak + stats.
  * QuizGrade  — a fresh grade returned by Claude (transient; folded into an Attempt).

Back-compat: ``QuizState.from_dict`` tolerantly upgrades the v1 store
(``history`` as ``[[iso, grade], …]``, no ``stats``) so an existing
``~/.claude/ccdashboard/quizme.json`` keeps its streak/history.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Constants (SM-2)
# --------------------------------------------------------------------------- #

EF_INITIAL = 2.5
EF_FLOOR = 1.3
PASS_QUALITY = 3            # SM-2 quality >= 3 is a pass
SCHEMA_VERSION = 2          # v1 = live-question store; v2 = generated decks
_ATTEMPT_TEXT_CAP = 2_000   # cap question/answer text persisted per attempt


# --------------------------------------------------------------------------- #
# Deterministic id / hash helpers (pure)
# --------------------------------------------------------------------------- #


def make_card_id(source: str, question: str) -> str:
    """Stable 16-hex id for a card, derived from its note path + question text.

    Editing a card's question yields a new id (and thus a fresh SM-2 schedule),
    which is the desired behavior when a deck is regenerated.
    """
    raw = f"{source}\n{question}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def content_hash(text: str) -> str:
    """16-hex content hash of a note's raw text (for incremental regeneration)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cap(text: str, limit: int = _ATTEMPT_TEXT_CAP) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# FlashCard — the unit of study (generated, persisted in a Markdown deck)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FlashCard:
    """One generated question/answer card (immutable)."""

    card_id: str
    source: str          # note path relative to its notes root, e.g. "Backend/EFCORE.md"
    concept: str         # short transferable-concept label, e.g. "DI lifetimes"
    question: str
    answer: str
    note_hash: str = ""  # content_hash() of the source note this card came from

    @classmethod
    def create(
        cls, source: str, concept: str, question: str, answer: str, note_hash: str = ""
    ) -> "FlashCard":
        """Build a card, computing its stable ``card_id`` from source + question."""
        return cls(
            card_id=make_card_id(source, question),
            source=source,
            concept=concept.strip(),
            question=question.strip(),
            answer=answer.strip(),
            note_hash=note_hash,
        )

    @property
    def title(self) -> str:
        name = Path(self.source).name
        return f"{name} · {self.concept}" if self.concept else name

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "source": self.source,
            "concept": self.concept,
            "question": self.question,
            "answer": self.answer,
            "note_hash": self.note_hash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FlashCard":
        source = str(d.get("source", ""))
        question = str(d.get("question", ""))
        cid = str(d.get("card_id") or make_card_id(source, question))
        return cls(
            card_id=cid,
            source=source,
            concept=str(d.get("concept", "")),
            question=question,
            answer=str(d.get("answer", "")),
            note_hash=str(d.get("note_hash", "")),
        )


# --------------------------------------------------------------------------- #
# Attempt — one graded answer to a card (immutable; full Q/A retained)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Attempt:
    """A single graded answer to a card, so progress on one card is reviewable."""

    date: str            # ISO "YYYY-MM-DD"
    question: str
    answer: str
    grade: int           # 0..5 (SM-2 quality)
    verdict: str = ""    # "correct" / "partial" / "incorrect"
    feedback: str = ""

    @classmethod
    def create(
        cls, date: str, question: str, answer: str, grade: int,
        verdict: str = "", feedback: str = "",
    ) -> "Attempt":
        return cls(
            date=date,
            question=_cap(question),
            answer=_cap(answer),
            grade=int(grade),
            verdict=verdict,
            feedback=_cap(feedback),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "question": self.question,
            "answer": self.answer,
            "grade": self.grade,
            "verdict": self.verdict,
            "feedback": self.feedback,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Attempt":
        return cls(
            date=str(d.get("date", "")),
            question=str(d.get("question", "")),
            answer=str(d.get("answer", "")),
            grade=int(d.get("grade", 0)),
            verdict=str(d.get("verdict", "")),
            feedback=str(d.get("feedback", "")),
        )

    @classmethod
    def from_legacy(cls, pair: Any) -> "Attempt | None":
        """Upgrade a v1 ``[iso_date, grade]`` history entry to an Attempt (no Q/A)."""
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            try:
                return cls(date=str(pair[0]), question="", answer="", grade=int(pair[1]))
            except (TypeError, ValueError):
                return None
        return None


# --------------------------------------------------------------------------- #
# CardState — SM-2 schedule + Attempt history for one card (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CardState:
    """SM-2 scheduling state for a card (immutable, round-trippable)."""

    ease: float = EF_INITIAL
    interval: int = 0                       # days until next review
    reps: int = 0                           # consecutive successful recalls
    due: str = ""                           # ISO date; "" == brand new
    last_grade: int | None = None
    history: tuple[Attempt, ...] = ()

    @property
    def is_new(self) -> bool:
        return not self.due

    def to_dict(self) -> dict[str, Any]:
        return {
            "ease": self.ease,
            "interval": self.interval,
            "reps": self.reps,
            "due": self.due,
            "last_grade": self.last_grade,
            "history": [a.to_dict() for a in self.history],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CardState":
        raw_hist = d.get("history", [])
        attempts: list[Attempt] = []
        for h in raw_hist:
            if isinstance(h, dict):
                attempts.append(Attempt.from_dict(h))
            else:  # v1 [iso, grade] tuple
                legacy = Attempt.from_legacy(h)
                if legacy is not None:
                    attempts.append(legacy)
        return cls(
            ease=float(d.get("ease", EF_INITIAL)),
            interval=int(d.get("interval", 0)),
            reps=int(d.get("reps", 0)),
            due=str(d.get("due", "")),
            last_grade=(int(d["last_grade"]) if d.get("last_grade") is not None else None),
            history=tuple(attempts),
        )


# --------------------------------------------------------------------------- #
# Streak — daily-quiz streak (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Streak:
    """Daily-quiz streak record (immutable)."""

    count: int = 0
    longest: int = 0
    last_session: str = ""     # ISO date of last answered day; "" == never

    def to_dict(self) -> dict[str, Any]:
        return {"count": self.count, "longest": self.longest, "last_session": self.last_session}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Streak":
        return cls(
            count=int(d.get("count", 0)),
            longest=int(d.get("longest", 0)),
            last_session=str(d.get("last_session", "")),
        )


# --------------------------------------------------------------------------- #
# Stats — lifetime "high score" totals (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Stats:
    """Lifetime quiz totals for the high-score display (immutable)."""

    total_answered: int = 0
    total_correct: int = 0
    best_day_count: int = 0
    best_day_date: str = ""
    today_count: int = 0       # answers given on ``today_date`` (drives best_day)
    today_date: str = ""

    @property
    def accuracy(self) -> float:
        return (self.total_correct / self.total_answered) if self.total_answered else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_answered": self.total_answered,
            "total_correct": self.total_correct,
            "best_day_count": self.best_day_count,
            "best_day_date": self.best_day_date,
            "today_count": self.today_count,
            "today_date": self.today_date,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Stats":
        return cls(
            total_answered=int(d.get("total_answered", 0)),
            total_correct=int(d.get("total_correct", 0)),
            best_day_count=int(d.get("best_day_count", 0)),
            best_day_date=str(d.get("best_day_date", "")),
            today_count=int(d.get("today_count", 0)),
            today_date=str(d.get("today_date", "")),
        )

    def record(self, passed: bool, today_iso: str) -> "Stats":
        """Return a NEW Stats after one answer (pure): bumps totals + best-day."""
        today_count = self.today_count + 1 if self.today_date == today_iso else 1
        best_count, best_date = self.best_day_count, self.best_day_date
        if today_count > best_count:
            best_count, best_date = today_count, today_iso
        return replace(
            self,
            total_answered=self.total_answered + 1,
            total_correct=self.total_correct + (1 if passed else 0),
            best_day_count=best_count,
            best_day_date=best_date,
            today_count=today_count,
            today_date=today_iso,
        )


# --------------------------------------------------------------------------- #
# QuizState — the whole persisted store (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class QuizState:
    """Per-card SM-2 states + the daily streak + lifetime stats (immutable)."""

    cards: dict[str, CardState] = field(default_factory=dict)
    streak: Streak = field(default_factory=Streak)
    stats: Stats = field(default_factory=Stats)
    version: int = SCHEMA_VERSION

    def card_state(self, card_id: str) -> CardState:
        return self.cards.get(card_id, CardState())

    def with_card(self, card_id: str, state: CardState) -> "QuizState":
        new_cards = dict(self.cards)
        new_cards[card_id] = state
        return replace(self, cards=new_cards)

    def with_streak(self, streak: Streak) -> "QuizState":
        return replace(self, streak=streak)

    def with_stats(self, stats: Stats) -> "QuizState":
        return replace(self, stats=stats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "streak": self.streak.to_dict(),
            "stats": self.stats.to_dict(),
            "cards": {cid: st.to_dict() for cid, st in self.cards.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QuizState":
        cards = {
            str(cid): CardState.from_dict(st)
            for cid, st in (d.get("cards") or {}).items()
            if isinstance(st, dict)
        }
        return cls(
            cards=cards,
            streak=Streak.from_dict(d.get("streak") or {}),
            stats=Stats.from_dict(d.get("stats") or {}),
            version=int(d.get("version", SCHEMA_VERSION)),
        )


# --------------------------------------------------------------------------- #
# QuizGrade — a fresh grade from Claude (transient; folded into an Attempt)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class QuizGrade:
    """Structured grade for one answer (immutable)."""

    grade: int            # 0..5 (SM-2 quality)
    verdict: str          # short label, e.g. "correct" / "partial" / "incorrect"
    feedback: str         # one or two sentences

    @property
    def passed(self) -> bool:
        return self.grade >= PASS_QUALITY
