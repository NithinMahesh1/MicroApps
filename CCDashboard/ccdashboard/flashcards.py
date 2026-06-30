"""
flashcards.py — deck generation + storage engine for CCDashboard QuizMe v2.

Generates Q&A flash cards from the user's ``.md`` study notes (via Claude Sonnet),
stores them as human-readable Markdown decks under
``~/.claude/ccdashboard/flashcards/``, and reloads them on startup without any
Claude call.

UI-agnostic, pure stdlib except the Claude call. The ``anthropic`` import is
LAZY (inside gen_cards) so importing this module never requires the SDK or
the network.

Public API
----------
Storage paths:
  * flashcards_dir() -> Path
  * deck_path(source) -> Path

Availability:
  * is_available() -> bool

Markdown round-trip:
  * serialize_deck(deck) -> str
  * parse_deck(text) -> Deck

Persistence (no Claude):
  * save_deck(deck) -> Path
  * load_deck(path) -> Deck | None
  * load_decks() -> list[FlashCard]

Claude-backed generation:
  * gen_cards(source, note_text, note_hash) -> list[FlashCard]
    (raises FlashcardsUnavailable when key/SDK missing)

Incremental build:
  * deck_is_current(source, note_hash) -> bool
  * build_decks(notes_dirs, progress_cb, force) -> BuildResult
  * regenerate_note(notes_dirs, source) -> list[FlashCard]
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ccdashboard.models import FlashCard, content_hash

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

GEN_MODEL = "claude-sonnet-4-6"
_MAX_NOTE_CHARS = 12_000   # cap note text sent to Claude
_MIN_NOTE_CHARS = 200      # skip near-empty notes
_MAX_CARDS_PER_NOTE = 8
_DECK_VERSION = 2

# Regex to extract metadata from the leading HTML comment
_META_RE = re.compile(
    r'<!--\s*ccd-flashcards\s+v=\d+\s+'
    r'source="([^"]*)"\s+'
    r'note_hash="([^"]*)"\s+'
    r'model="([^"]*)"\s+'
    r'generated="([^"]*)"\s*-->'
)


# --------------------------------------------------------------------------- #
# Error type
# --------------------------------------------------------------------------- #


class FlashcardsUnavailable(RuntimeError):
    """Raised when a Claude-backed call cannot run (e.g. ANTHROPIC_API_KEY unset)."""


# --------------------------------------------------------------------------- #
# Availability + lazy client
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
    """Construct a sync Anthropic client or raise FlashcardsUnavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise FlashcardsUnavailable("Set ANTHROPIC_API_KEY to enable flashcard generation.")
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise FlashcardsUnavailable("The 'anthropic' package is not installed.") from exc
    return anthropic.Anthropic(api_key=api_key)


# --------------------------------------------------------------------------- #
# Storage paths
# --------------------------------------------------------------------------- #


def flashcards_dir() -> Path:
    """User-level storage directory for all Markdown deck files."""
    return Path.home() / ".claude" / "ccdashboard" / "flashcards"


def deck_path(source: str) -> Path:
    """Deterministic, collision-resistant path for the deck file of *source*.

    Slugify the note's relative POSIX path (e.g. ``"Backend/EFCORE.md"``) by
    replacing ``/`` and ``\\`` with ``__`` and stripping the trailing ``.md``,
    then append ``.md`` (e.g. ``Backend__EFCORE.md``).  The transform is
    stable and reversible enough to avoid collisions between notes in different
    subdirectories.
    """
    slug = source.replace("/", "__").replace("\\", "__")
    if slug.endswith(".md"):
        slug = slug[:-3]
    return flashcards_dir() / f"{slug}.md"


# --------------------------------------------------------------------------- #
# Immutable result records (frozen + slotted)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Deck:
    """An immutable loaded/generated deck of flash cards."""

    source: str                   # relative note path, e.g. "Backend/EFCORE.md"
    note_hash: str                # content_hash() of the source note
    cards: tuple[FlashCard, ...]  # ordered flash cards
    model: str = ""               # generation model id
    generated: str = ""           # ISO-8601 UTC timestamp of last generation


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Per-note counts returned by :func:`build_decks`."""

    total: int      # notes considered (all .md files found)
    generated: int  # notes (re)generated via Claude
    skipped: int    # notes skipped (unchanged hash or too short)
    failed: int     # notes that raised during gen/save (build continues)
    cards: int      # total cards now on disk (from load_decks after build)


# --------------------------------------------------------------------------- #
# Markdown deck serialization / parsing
# --------------------------------------------------------------------------- #


def serialize_deck(deck: Deck) -> str:
    """Render *deck* to the human-readable Markdown deck format.

    Format::

        <!-- ccd-flashcards v=2 source="..." note_hash="..." model="..." generated="..." -->
        # Flashcards — <source>

        ## Concept: <concept>
        **Q:** <question>

        **A:** <answer>
    """
    lines: list[str] = [
        f'<!-- ccd-flashcards v={_DECK_VERSION} source="{deck.source}"'
        f' note_hash="{deck.note_hash}"'
        f' model="{deck.model}"'
        f' generated="{deck.generated}" -->',
        f"# Flashcards — {deck.source}",
        "",
    ]
    for card in deck.cards:
        lines += [
            f"## Concept: {card.concept}",
            f"**Q:** {card.question}",
            "",
            f"**A:** {card.answer}",
            "",
        ]
    return "\n".join(lines)


def _parse_card_block(block: str, source: str, note_hash: str) -> FlashCard | None:
    """Extract one :class:`FlashCard` from a raw block (after ``## Concept:`` is stripped).

    Returns ``None`` if the block is malformed or missing Q/A.  Never raises.
    """
    try:
        lines = block.split("\n", 1)
        concept = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""

        # Question: from **Q:** up to the line(s) containing **A:**
        q_match = re.search(r"\*\*Q:\*\*\s*(.*?)(?=\n+\*\*A:\*\*)", body, re.DOTALL)
        # Answer: everything after **A:**
        a_match = re.search(r"\*\*A:\*\*\s*(.*)", body, re.DOTALL)

        if not q_match or not a_match:
            return None

        question = q_match.group(1).strip()
        answer = a_match.group(1).strip()

        if not question or not answer:
            return None

        return FlashCard.create(source, concept, question, answer, note_hash)
    except Exception:  # noqa: BLE001
        return None


def parse_deck(text: str) -> Deck:
    """Parse a Markdown deck file into a :class:`Deck`.

    Tolerant: returns a ``Deck`` with empty ``cards`` on malformed or empty
    input; never raises.
    """
    if not text or not text.strip():
        return Deck(source="", note_hash="", cards=())

    # --- metadata from leading HTML comment ---
    source = note_hash = model = generated = ""
    m = _META_RE.search(text)
    if m:
        source, note_hash, model, generated = (
            m.group(1), m.group(2), m.group(3), m.group(4)
        )

    # --- split on "## Concept:" at the start of any line ---
    # parts[0] is the file header; parts[1:] are concept blocks where
    # the first line of each block is the concept name.
    parts = re.split(r"^## Concept:\s*", text, flags=re.MULTILINE)
    if len(parts) < 2:
        return Deck(source=source, note_hash=note_hash, cards=(),
                    model=model, generated=generated)

    cards: list[FlashCard] = []
    for block in parts[1:]:
        card = _parse_card_block(block.strip(), source, note_hash)
        if card is not None:
            cards.append(card)

    return Deck(
        source=source,
        note_hash=note_hash,
        cards=tuple(cards),
        model=model,
        generated=generated,
    )


# --------------------------------------------------------------------------- #
# Atomic save / load
# --------------------------------------------------------------------------- #


def save_deck(deck: Deck) -> Path:
    """Atomically write *deck* to disk (temp-file + os.replace); create parent dirs."""
    dest = deck_path(deck.source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = serialize_deck(deck)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def load_deck(path: Path) -> Deck | None:
    """Read + parse a deck file; return ``None`` on any read error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_deck(text)


def load_decks() -> list[FlashCard]:
    """Load ALL cards from every ``*.md`` in :func:`flashcards_dir`.

    Returns a flat list de-duped by ``card_id`` (first seen wins).
    Returns ``[]`` when the directory does not exist yet (first run).
    This is the offline startup call — no Claude invoked.
    """
    d = flashcards_dir()
    if not d.exists():
        return []
    seen: set[str] = set()
    cards: list[FlashCard] = []
    for path in sorted(d.glob("*.md")):
        deck = load_deck(path)
        if deck is None:
            continue
        for card in deck.cards:
            if card.card_id not in seen:
                seen.add(card.card_id)
                cards.append(card)
    return cards


# --------------------------------------------------------------------------- #
# Claude-backed generation (lazy import; single networked function)
# --------------------------------------------------------------------------- #


def gen_cards(source: str, note_text: str, note_hash: str) -> list[FlashCard]:
    """Generate flash cards from *note_text* via Claude Sonnet (structured output).

    Raises :class:`FlashcardsUnavailable` when ``ANTHROPIC_API_KEY`` is unset
    or the ``anthropic`` SDK is missing.  All other errors propagate to the
    caller (build_decks catches them per-note).
    """
    from pydantic import BaseModel  # lazy: not needed for offline usage

    class _GenCard(BaseModel):
        concept: str
        question: str
        answer: str

    class _DeckOut(BaseModel):
        cards: list[_GenCard]

    client = _client()
    resp = client.messages.parse(
        model=GEN_MODEL,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        output_format=_DeckOut,
        system=(
            "You write high-quality flash cards that test the TRANSFERABLE concept "
            "or understanding in the user's study note (not trivia, not yes/no). "
            "Generate 3–6 cards. Each card has:\n"
            "  • concept: a short label (≤6 words) naming the transferable idea,\n"
            "  • question: a focused question that tests real understanding,\n"
            "  • answer: a correct, concise answer.\n\n"
            "For code/implementation notes you MAY name general technologies "
            "(dependency injection, Swagger/OpenAPI, EF Core, REST, SM-2) "
            "but MUST NOT reference the user’s private identifiers: project class "
            "names, internal package names (e.g. *.Common, *.Infrastructure), "
            "repo-specific file paths, or ticket/PR numbers. "
            "Generalize away any such specifics."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Study note source: {source}\n\n"
                f"{note_text[:_MAX_NOTE_CHARS]}"
            ),
        }],
    )

    # Extract the parsed structured output from the response
    parsed: _DeckOut | None = None
    for block in resp.content:
        if (
            getattr(block, "type", "") == "text"
            and getattr(block, "parsed_output", None) is not None
        ):
            parsed = block.parsed_output
            break

    if parsed is None:
        reason = getattr(resp, "stop_reason", None)
        raise FlashcardsUnavailable(
            f"Claude returned no structured output (stop_reason={reason})."
        )

    cards: list[FlashCard] = []
    for gc in parsed.cards:
        if not gc.question.strip() or not gc.answer.strip():
            continue
        cards.append(
            FlashCard.create(source, gc.concept, gc.question, gc.answer, note_hash)
        )
        if len(cards) >= _MAX_CARDS_PER_NOTE:
            break

    return cards


# --------------------------------------------------------------------------- #
# Incremental build over notes folders
# --------------------------------------------------------------------------- #


def deck_is_current(source: str, note_hash: str) -> bool:
    """True iff a deck file exists for *source* whose stored ``note_hash`` matches."""
    path = deck_path(source)
    if not path.exists():
        return False
    deck = load_deck(path)
    if deck is None:
        return False
    return deck.note_hash == note_hash


def build_decks(
    notes_dirs: list[Path],
    progress_cb: Callable[[int, int, str], None] | None = None,
    force: bool = False,
) -> BuildResult:
    """Walk *notes_dirs*, (re)generating decks for changed or new notes.

    Args:
        notes_dirs:   Directories to scan recursively for ``*.md`` notes.
        progress_cb:  Optional ``(done, total, source)`` callback invoked after
                      each note, whether skipped, generated, or failed.
        force:        If ``True``, regenerate all decks even when current.

    Returns:
        :class:`BuildResult` with per-note counts and total cards on disk.
    """
    # Collect all note paths, de-duping by source (first directory wins)
    seen_sources: set[str] = set()
    note_pairs: list[tuple[Path, str]] = []  # (absolute path, posix source)
    for d in notes_dirs:
        if not d.exists():
            continue
        for path in sorted(d.rglob("*.md")):
            try:
                source = path.relative_to(d).as_posix()
            except ValueError:
                continue
            if source not in seen_sources:
                seen_sources.add(source)
                note_pairs.append((path, source))

    total = len(note_pairs)
    generated = skipped = failed = done = 0

    for path, source in note_pairs:
        # --- read note text ---
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            failed += 1
            done += 1
            if progress_cb is not None:
                progress_cb(done, total, source)
            continue

        # --- skip near-empty notes ---
        if len(text) < _MIN_NOTE_CHARS:
            skipped += 1
            done += 1
            if progress_cb is not None:
                progress_cb(done, total, source)
            continue

        # --- skip unchanged decks (unless force=True) ---
        h = content_hash(text)
        if not force and deck_is_current(source, h):
            skipped += 1
            done += 1
            if progress_cb is not None:
                progress_cb(done, total, source)
            continue

        # --- generate + save ---
        try:
            cards = gen_cards(source, text, h)
            generated_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            deck = Deck(
                source=source,
                note_hash=h,
                cards=tuple(cards),
                model=GEN_MODEL,
                generated=generated_iso,
            )
            save_deck(deck)
            generated += 1
        except Exception:  # noqa: BLE001 — per-note failure never aborts the build
            failed += 1

        done += 1
        if progress_cb is not None:
            progress_cb(done, total, source)

    return BuildResult(
        total=total,
        generated=generated,
        skipped=skipped,
        failed=failed,
        cards=len(load_decks()),
    )


def regenerate_note(notes_dirs: list[Path], source: str) -> list[FlashCard]:
    """Force-regenerate the deck for *source*; return its cards (or ``[]`` on error)."""
    for d in notes_dirs:
        candidate = d / Path(source)
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []
        h = content_hash(text)
        try:
            cards = gen_cards(source, text, h)
            generated_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            deck = Deck(
                source=source,
                note_hash=h,
                cards=tuple(cards),
                model=GEN_MODEL,
                generated=generated_iso,
            )
            save_deck(deck)
            return list(cards)
        except Exception:  # noqa: BLE001
            return []
    return []


# --------------------------------------------------------------------------- #
# Offline smoke (no Claude calls)
# --------------------------------------------------------------------------- #


if __name__ == "__main__":
    import sys

    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    _all_cards = load_decks()
    _fc_dir = flashcards_dir()
    _deck_count = len(list(_fc_dir.glob("*.md"))) if _fc_dir.exists() else 0
    print(
        f"Flashcards: {_deck_count} deck(s), {len(_all_cards)} card(s) on disk  "
        f"available={is_available()}"
    )
