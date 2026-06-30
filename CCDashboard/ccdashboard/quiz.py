"""
quiz.py — SM-2 scheduling, grading, streak, and selection engine for QuizMe v2.

UI-agnostic, mirroring the conversations.py / scan.py engine split. Pure stdlib
except the Claude grading call (grade_answer), which uses the anthropic SDK and
degrades gracefully when ANTHROPIC_API_KEY is unset.

Pipeline (v2 — pre-generated FlashCard decks; flashcards.py owns generation):
  * load_state() / save_state() -> round-trippable JSON store at
    ~/.claude/ccdashboard/quizme.json (dirs made on save, atomically).
  * select_today(state, cards, today)
                                -> FlashCard to quiz now (most-overdue first,
                                   else brand-new, else soonest upcoming).
  * select_next_practice(state, cards, today, exclude_ids)
                                -> FlashCard for free-practice mode.
  * review(state, quality, today) -> NEW CardState with SM-2 advanced (no
                                   history appended — apply_grade does that).
  * bump_streak(streak, today)  -> NEW Streak (reset on any skipped day).
  * grade_answer(card, answer)  -> QuizGrade {grade, verdict, feedback} (Claude
                                   Opus; raises QuizUnavailable w/o key).
  * apply_grade(state, card, grade, answer, today)
                                -> NEW QuizState: appends Attempt, advances SM-2,
                                   bumps streak, updates lifetime Stats.

SM-2 (strict variant): the new interval uses the OLD ease; EF is updated every
review and floored at 1.3; quality >= 3 passes, quality < 3 resets reps to 0
and interval to 1. Defaults ease=2.5 / interval=0 / reps=0.

The ``anthropic`` import is LAZY (inside grade_answer / _client) so importing
this module — and therefore the whole TUI — never requires the SDK or the network.
"""
from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# Re-exported models (so quiz.FlashCard, quiz.QuizState, etc. resolve for TUI)
# --------------------------------------------------------------------------- #

from ccdashboard.models import (  # noqa: E402
    FlashCard, Attempt, CardState, Streak, Stats, QuizState, QuizGrade,
    EF_INITIAL, EF_FLOOR, PASS_QUALITY, make_card_id,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

QUIZ_MODEL = "claude-opus-4-8"

# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class QuizUnavailable(RuntimeError):
    """Raised when a Claude-backed call cannot run (e.g. ANTHROPIC_API_KEY unset)."""


# --------------------------------------------------------------------------- #
# Notes-directory configuration (OUT OF REPO; managed by the QuizMe UI)
# --------------------------------------------------------------------------- #

_NOTES_DIR_ENV = "CCDASHBOARD_NOTES_DIR"


def _config_path() -> Path:
    return Path.home() / ".claude" / "ccdashboard" / "config.json"


def _default_notes_dir() -> Path:
    return Path.home() / "Learning" / "Codebase"


def expand_dir(raw: str) -> Path:
    """Expand ``~`` and ``$ENV`` vars in a configured path string."""
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def _dedup_dirs(dirs: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for d in dirs:
        if str(d) not in seen:
            seen.add(str(d))
            out.append(d)
    return out


def _read_config() -> dict[str, Any]:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _env_notes_dirs() -> list[Path]:
    raw = os.environ.get(_NOTES_DIR_ENV, "")
    return [expand_dir(p) for p in raw.split(os.pathsep) if p.strip()]


def load_notes_dirs() -> list[Path]:
    """Configured study-notes folders, in priority order:

    1. ``notesDirs`` in ~/.claude/ccdashboard/config.json (managed by the UI),
    2. else the ``CCDASHBOARD_NOTES_DIR`` env var (os.pathsep-separated),
    3. else the legacy default (~/Learning/Codebase).

    Paths are ~/env-expanded and de-duplicated. Existence is NOT required here;
    missing folders simply contribute no cards.
    """
    raw = _read_config().get("notesDirs")
    if isinstance(raw, list):
        dirs = [expand_dir(p) for p in raw if isinstance(p, str) and p.strip()]
        if dirs:
            return _dedup_dirs(dirs)
    env = _env_notes_dirs()
    if env:
        return _dedup_dirs(env)
    return [_default_notes_dir()]


def save_notes_dirs(dirs: list[Path] | list[str]) -> list[Path]:
    """Persist study-notes folders to the config file (atomic); return the saved
    list. An empty list clears the setting (falls back to env var / default)."""
    expanded = _dedup_dirs([expand_dir(str(d)) for d in dirs])
    cfg = _read_config()
    cfg["notesDirs"] = [str(d) for d in expanded]
    _write_json_atomic(_config_path(), cfg)
    return expanded


# --------------------------------------------------------------------------- #
# Persistent store (OUT OF REPO, atomic JSON)
# --------------------------------------------------------------------------- #


def _store_path() -> Path:
    return Path.home() / ".claude" / "ccdashboard" / "quizme.json"


def _write_json_atomic(p: Path, obj: Any) -> None:
    """Atomically write *obj* as pretty JSON, creating parent dirs on first use."""
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
    _write_json_atomic(path or _store_path(), state.to_dict())


# --------------------------------------------------------------------------- #
# SM-2 math helpers (pure)
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


# --------------------------------------------------------------------------- #
# SM-2 scheduling (pure; no mutation; return NEW objects)
# --------------------------------------------------------------------------- #


def review(state: CardState, quality: int, today: date) -> CardState:
    """Return a NEW CardState with SM-2 advanced (interval uses the OLD ease).

    Does NOT append to ``history`` — ``apply_grade`` does that after calling
    this function so the Attempt can carry the full question/answer text.
    """
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
    return dataclasses.replace(
        state, ease=ease, interval=interval, reps=reps, due=due,
        last_grade=quality,
        # history is intentionally NOT updated here; apply_grade appends the Attempt
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


def due_count(state: QuizState, cards: list[FlashCard], today: date) -> int:
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


def select_today(
    state: QuizState, cards: list[FlashCard], today: date
) -> FlashCard | None:
    """Pick today's card: most-overdue first (lowest ease breaks ties), else a
    brand-new card, else the soonest upcoming card (so the tab is never empty).

    Does NOT consult the daily gate — the caller checks ``answered_today`` to
    decide whether to present this card or show "come back tomorrow".
    """
    if not cards:
        return None
    due: list[tuple[date, float, FlashCard]] = []
    fresh: list[FlashCard] = []
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


def select_next_practice(
    state: QuizState,
    cards: list[FlashCard],
    today: date,
    exclude_ids: frozenset[str] = frozenset(),
) -> FlashCard | None:
    """Free-practice card picker: deterministic, no randomness.

    Among cards whose ``card_id`` is not in ``exclude_ids``:
      1. Most-overdue (due <= today): earliest due, then lowest ease.
      2. First brand-new (source order).
      3. Soonest-upcoming card (lowest due date).

    Returns ``None`` if every card is excluded.
    """
    eligible = [c for c in cards if c.card_id not in exclude_ids]
    if not eligible:
        return None
    due: list[tuple[date, float, FlashCard]] = []
    fresh: list[FlashCard] = []
    for c in eligible:
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
        ((_parse_date(state.card_state(c.card_id).due), c) for c in eligible),
        key=lambda t: (t[0] or date.max),
    )
    return upcoming[0][1] if upcoming else None


def next_due_date(state: QuizState, cards: list[FlashCard]) -> str:
    """ISO date of the soonest upcoming review, or '' if none scheduled."""
    dates = [
        d for d in (_parse_date(state.card_state(c.card_id).due) for c in cards)
        if d is not None
    ]
    return min(dates).isoformat() if dates else ""


def apply_grade(
    state: QuizState,
    card: FlashCard,
    grade: QuizGrade,
    answer: str,
    today: date,
) -> QuizState:
    """Single transactional advance: append Attempt, advance SM-2, bump streak,
    update Stats. Returns a NEW QuizState (no mutation of ``state``)."""
    attempt = Attempt.create(
        today.isoformat(), card.question, answer,
        grade.grade, grade.verdict, grade.feedback,
    )
    new_cs = review(state.card_state(card.card_id), grade.grade, today)
    new_cs = dataclasses.replace(new_cs, history=new_cs.history + (attempt,))
    new_streak = bump_streak(state.streak, today)
    new_stats = state.stats.record(grade.passed, today.isoformat())
    return state.with_card(card.card_id, new_cs).with_streak(new_streak).with_stats(new_stats)


# --------------------------------------------------------------------------- #
# Claude-backed grading (lazy import; degrades gracefully)
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


def grade_answer(card: FlashCard, answer: str) -> QuizGrade:
    """Grade a free-text answer against the card's stored question/answer (Claude).

    Uses the card's own ``question`` and ``answer`` as the reference — no separate
    question argument needed in v2. Raises ``QuizUnavailable`` when the key is unset.
    """
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
            "Grade the user's answer using the SM-2 0..5 quality scale "
            "(5 perfect, 3 the barely-correct pass threshold, <3 a fail). "
            "Be fair, specific, and concise."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"QUESTION:\n{card.question}\n\n"
                f"CANONICAL ANSWER:\n{card.answer}\n\n"
                f"USER ANSWER:\n{answer}"
            ),
        }],
    )
    parsed = None
    for block in resp.content:
        if (
            getattr(block, "type", "") == "text"
            and getattr(block, "parsed_output", None) is not None
        ):
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
    _st = load_state()
    _today = date.today()
    print(
        f"Streak: {_st.streak.count} (longest {_st.streak.longest})  "
        f"Stats: {_st.stats.total_answered} answered, "
        f"{_st.stats.accuracy:.0%} accuracy  "
        f"available={is_available()}"
    )
