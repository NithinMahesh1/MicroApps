"""
quiz.py — daily spaced-repetition quiz engine over the user's study notes.

UI-agnostic, mirroring the conversations.py / scan.py engine split. Pure stdlib
except the two Claude calls (gen_question / grade_answer), which use the
anthropic SDK and degrade gracefully when ANTHROPIC_API_KEY is unset.

Pipeline:
  * load_cards(notes_dir)       -> split every *.md into Card records (per ``##``
                                   section, else whole file). Pure, offline,
                                   deterministic ids.
  * load_state() / save_state() -> round-trippable JSON store OUTSIDE the repo at
                                   ~/.claude/ccdashboard/quizme.json (dirs made on
                                   save, atomically).
  * select_today(state, cards)  -> the card to quiz now (most-overdue first, else a
                                   brand-new card, else the soonest upcoming).
  * review(state, quality, today) -> NEW CardState with SM-2 advanced (no mutation).
  * bump_streak(streak, today)  -> NEW Streak (reset on any skipped day).
  * apply_grade(...)            -> NEW QuizState: advances SM-2 + bumps streak.
  * gen_question(card)          -> str  (Claude; raises QuizUnavailable w/o key).
  * grade_answer(card, q, ans)  -> QuizGrade {grade, verdict, feedback} (Claude).

SM-2 (strict variant): the new interval uses the OLD ease; EF is updated every
review and floored at 1.3; quality >= 3 passes, quality < 3 resets reps to 0 and
interval to 1. Defaults ease=2.5 / interval=0 / reps=0.

The ``anthropic`` import is LAZY (inside the Claude-backed functions) so importing
this module — and therefore the whole TUI — never requires the SDK or the network.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

QUIZ_MODEL = "claude-opus-4-8"
EF_INITIAL = 2.5
EF_FLOOR = 1.3
PASS_QUALITY = 3
_SCHEMA_VERSION = 1
_MAX_CARD_CHARS = 8_000  # cap one card's note text sent to Claude
_MIN_BODY_CHARS = 40     # skip near-empty section stubs
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")  # split on ## / ### (not the H1)


def _default_notes_dir() -> Path:
    return Path.home() / "Learning" / "Codebase"


def _store_path() -> Path:
    return Path.home() / ".claude" / "ccdashboard" / "quizme.json"


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class QuizUnavailable(RuntimeError):
    """Raised when a Claude-backed call cannot run (e.g. ANTHROPIC_API_KEY unset)."""


# --------------------------------------------------------------------------- #
# Immutable records (frozen / slotted)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Card:
    """One study card extracted from a note section (immutable)."""

    card_id: str
    source: str          # relative note path, e.g. "Backend/EFCORE.md"
    heading: str         # the ## heading, or "(whole file)"
    body: str            # markdown body for this card (capped at load time)

    @property
    def title(self) -> str:
        name = Path(self.source).name
        if self.heading == "(whole file)":
            return name
        return f"{name} · {self.heading}"


@dataclass(frozen=True, slots=True)
class CardState:
    """SM-2 scheduling state for a card (immutable, round-trippable)."""

    ease: float = EF_INITIAL
    interval: int = 0                       # days until next review
    reps: int = 0                           # consecutive successful recalls
    due: str = ""                           # ISO date "YYYY-MM-DD"; "" == brand new
    last_grade: int | None = None
    history: tuple[tuple[str, int], ...] = ()   # ((iso_date, grade), ...)

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
            "history": [list(h) for h in self.history],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CardState":
        hist = tuple(
            (str(h[0]), int(h[1]))
            for h in d.get("history", [])
            if isinstance(h, (list, tuple)) and len(h) == 2
        )
        return cls(
            ease=float(d.get("ease", EF_INITIAL)),
            interval=int(d.get("interval", 0)),
            reps=int(d.get("reps", 0)),
            due=str(d.get("due", "")),
            last_grade=(int(d["last_grade"]) if d.get("last_grade") is not None else None),
            history=hist,
        )


@dataclass(frozen=True, slots=True)
class Streak:
    """Daily-quiz streak record (immutable)."""

    count: int = 0
    longest: int = 0
    last_session: str = ""     # ISO date of last answered day; "" == never

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "longest": self.longest,
            "last_session": self.last_session,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Streak":
        return cls(
            count=int(d.get("count", 0)),
            longest=int(d.get("longest", 0)),
            last_session=str(d.get("last_session", "")),
        )


@dataclass(frozen=True, slots=True)
class QuizState:
    """Whole persisted store: per-card SM-2 states + the daily streak (immutable)."""

    cards: dict[str, CardState] = field(default_factory=dict)
    streak: Streak = field(default_factory=Streak)
    version: int = _SCHEMA_VERSION

    def card_state(self, card_id: str) -> CardState:
        return self.cards.get(card_id, CardState())

    def with_card(self, card_id: str, state: CardState) -> "QuizState":
        new_cards = dict(self.cards)
        new_cards[card_id] = state
        return replace(self, cards=new_cards)

    def with_streak(self, streak: Streak) -> "QuizState":
        return replace(self, streak=streak)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "streak": self.streak.to_dict(),
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
            version=int(d.get("version", _SCHEMA_VERSION)),
        )


@dataclass(frozen=True, slots=True)
class QuizGrade:
    """Structured grade for one answer (immutable)."""

    grade: int            # 0..5 (SM-2 quality)
    verdict: str          # short label, e.g. "correct" / "partial" / "incorrect"
    feedback: str         # one or two sentences


# --------------------------------------------------------------------------- #
# Card extraction (pure / offline)
# --------------------------------------------------------------------------- #


def _card_id(source: str, heading: str) -> str:
    raw = f"{source}#{heading}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _split_note(rel_path: str, text: str) -> list[Card]:
    """Split one note into cards by ## / ### sections; whole-file fallback."""
    sections: list[tuple[str, list[str]]] = []
    current_head = "(whole file)"
    current_body: list[str] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            if "".join(current_body).strip():
                sections.append((current_head, current_body))
            current_head = m.group(2).strip()
            current_body = []
        else:
            current_body.append(line)
    if "".join(current_body).strip():
        sections.append((current_head, current_body))

    cards: list[Card] = []
    for head, body_lines in sections:
        body = "\n".join(body_lines).strip()
        if len(body) < _MIN_BODY_CHARS:
            continue
        cards.append(
            Card(
                card_id=_card_id(rel_path, head),
                source=rel_path,
                heading=head,
                body=body[:_MAX_CARD_CHARS],
            )
        )
    return cards


def load_cards(notes_dir: Path | None = None) -> list[Card]:
    """Read every ``*.md`` under ``notes_dir`` into Card records (sorted by source)."""
    root = notes_dir or _default_notes_dir()
    if not root.exists():
        return []
    cards: list[Card] = []
    for path in sorted(root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()
        cards.extend(_split_note(rel, text))
    return cards


# --------------------------------------------------------------------------- #
# Persistent store (OUT OF REPO, atomic JSON)
# --------------------------------------------------------------------------- #


def load_state(path: Path | None = None) -> QuizState:
    """Load the store; return an empty QuizState if missing or unreadable."""
    p = path or _store_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return QuizState()
    if not isinstance(data, dict):
        return QuizState()
    return QuizState.from_dict(data)


def save_state(state: QuizState, path: Path | None = None) -> None:
    """Atomically write the store, creating ~/.claude/ccdashboard on first use."""
    p = path or _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# --------------------------------------------------------------------------- #
# SM-2 + streak + selection (pure)
# --------------------------------------------------------------------------- #


def _parse_date(iso: str) -> date | None:
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return None


def _ease_delta(quality: int) -> float:
    """Canonical SM-2 ease change for quality 0..5 (only q=5 grows EF)."""
    return 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)


def review(state: CardState, quality: int, today: date) -> CardState:
    """Return a NEW CardState with SM-2 advanced (interval uses the OLD ease)."""
    if not 0 <= quality <= 5:
        raise ValueError("quality must be 0..5")
    if quality >= PASS_QUALITY:
        if state.reps == 0:
            interval = 1
        elif state.reps == 1:
            interval = 6
        else:
            interval = max(1, round(state.interval * state.ease))
        reps = state.reps + 1
    else:                                       # failed -> relearn tomorrow
        interval = 1
        reps = 0
    ease = max(EF_FLOOR, state.ease + _ease_delta(quality))
    due = (today + timedelta(days=interval)).isoformat()
    history = state.history + ((today.isoformat(), quality),)
    return replace(
        state, ease=ease, interval=interval, reps=reps, due=due,
        last_grade=quality, history=history,
    )


def bump_streak(streak: Streak, today: date) -> Streak:
    """Advance the daily streak; reset to 1 if a calendar day was skipped."""
    last = _parse_date(streak.last_session)
    if last == today:
        return streak                           # already counted today
    if last is not None and today == last + timedelta(days=1):
        count = streak.count + 1
    else:
        count = 1
    return Streak(
        count=count,
        longest=max(streak.longest, count),
        last_session=today.isoformat(),
    )


def answered_today(streak: Streak, today: date) -> bool:
    return _parse_date(streak.last_session) == today


def due_count(state: QuizState, cards: list[Card], today: date) -> int:
    """Count cards that are brand-new or due on/before ``today``."""
    n = 0
    for c in cards:
        st = state.card_state(c.card_id)
        if st.is_new:
            n += 1
            continue
        d = _parse_date(st.due)
        if d is not None and d <= today:
            n += 1
    return n


def select_today(state: QuizState, cards: list[Card], today: date) -> Card | None:
    """Pick today's card: most-overdue first (lowest ease breaks ties), else a
    brand-new card, else the soonest upcoming card (so the tab is never empty).

    Does NOT consult the daily gate — the caller checks ``answered_today`` to
    decide whether to present this card or show "come back tomorrow".
    """
    if not cards:
        return None
    due: list[tuple[date, float, Card]] = []
    fresh: list[Card] = []
    for c in cards:
        st = state.card_state(c.card_id)
        if st.is_new:
            fresh.append(c)
            continue
        d = _parse_date(st.due)
        if d is not None and d <= today:
            due.append((d, st.ease, c))
    if due:
        due.sort(key=lambda t: (t[0], t[1]))    # earliest due, then lowest ease
        return due[0][2]
    if fresh:
        return fresh[0]                          # deterministic: first by source order
    upcoming = sorted(
        ((_parse_date(state.card_state(c.card_id).due), c) for c in cards),
        key=lambda t: (t[0] or date.max),
    )
    return upcoming[0][1] if upcoming else None


def next_due_date(state: QuizState, cards: list[Card]) -> str:
    """ISO date of the soonest upcoming review, or '' if none scheduled."""
    dates = [
        d for d in (_parse_date(state.card_state(c.card_id).due) for c in cards)
        if d is not None
    ]
    return min(dates).isoformat() if dates else ""


def apply_grade(state: QuizState, card: Card, quality: int, today: date) -> QuizState:
    """Advance the card's SM-2 state AND bump the streak; return a NEW QuizState."""
    new_card_state = review(state.card_state(card.card_id), quality, today)
    new_streak = bump_streak(state.streak, today)
    return state.with_card(card.card_id, new_card_state).with_streak(new_streak)


# --------------------------------------------------------------------------- #
# Claude-backed generation + grading (lazy import; degrades gracefully)
# --------------------------------------------------------------------------- #


def is_available() -> bool:
    """True iff a Claude call could run right now (key present + SDK importable)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _client():
    """Construct a sync Anthropic client or raise QuizUnavailable (never TypeError)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise QuizUnavailable("Set ANTHROPIC_API_KEY to enable QuizMe.")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise QuizUnavailable("The 'anthropic' package is not installed.") from exc
    return anthropic.Anthropic(api_key=api_key)


def _first_text(resp: Any) -> str:
    return next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "").strip()


def gen_question(card: Card) -> str:
    """Generate ONE focused quiz question from the card's note (Claude)."""
    client = _client()
    resp = client.messages.create(
        model=QUIZ_MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        system=(
            "You write ONE focused quiz question that tests real understanding of "
            "the user's study note (not trivia, not yes/no). Output ONLY the "
            "question text — no preamble, no answer, no markdown headers."
        ),
        messages=[{
            "role": "user",
            "content": f"NOTE ({card.title}):\n\n{card.body}",
        }],
    )
    q = _first_text(resp)
    if not q:
        raise QuizUnavailable("Claude returned no question — try again.")
    return q


def grade_answer(card: Card, question: str, answer: str) -> QuizGrade:
    """Grade a free-text answer against the source note (Claude, structured)."""
    from pydantic import BaseModel, Field

    class _Grade(BaseModel):
        grade: int = Field(ge=0, le=5, description="0=wrong … 5=fully correct (SM-2 quality)")
        verdict: str = Field(description="one short label: correct / partial / incorrect")
        feedback: str = Field(description="one or two sentences of specific feedback")

    client = _client()
    resp = client.messages.parse(
        model=QUIZ_MODEL,
        max_tokens=1024,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        output_format=_Grade,
        system=(
            "Grade the user's answer against the source note using the SM-2 0..5 "
            "quality scale (5 perfect, 3 the barely-correct pass threshold, <3 a "
            "fail). Be fair, specific, and concise."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"SOURCE NOTE ({card.title}):\n{card.body}\n\n"
                f"QUESTION:\n{question}\n\nUSER ANSWER:\n{answer}"
            ),
        }],
    )
    parsed = None
    for block in resp.content:
        if getattr(block, "type", "") == "text" and getattr(block, "parsed_output", None) is not None:
            parsed = block.parsed_output
            break
    if parsed is None:
        reason = getattr(resp, "stop_reason", None)
        raise QuizUnavailable(f"Could not grade the answer (stop_reason={reason}).")
    return QuizGrade(
        grade=int(parsed.grade),
        verdict=str(parsed.verdict),
        feedback=str(parsed.feedback),
    )


if __name__ == "__main__":  # offline smoke test (no Claude calls)
    import sys

    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    _cards = load_cards()
    print(f"Loaded {len(_cards)} cards from {_default_notes_dir()}")
    _st = load_state()
    _today = date.today()
    print(
        f"Streak: {_st.streak.count} (longest {_st.streak.longest})  "
        f"due={due_count(_st, _cards, _today)}  available={is_available()}"
    )
    _pick = select_today(_st, _cards, _today)
    print("Today's card:", _pick.title if _pick else "—")
