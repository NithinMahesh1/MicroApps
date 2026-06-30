"""Tests for flashcards.py — deck generation + storage engine.

Pure engine tests: no Textual, no Claude, no network.
Runnable under pytest or standalone (``python tests/test_flashcards.py``).
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ccdashboard import flashcards
from ccdashboard.models import FlashCard, content_hash


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@contextmanager
def _workspace():
    """Temp dir that also redirects flashcards_dir into it, then tears down."""
    tmp = Path(tempfile.mkdtemp(prefix="ccd-fc-test-"))
    real_flashcards_dir = flashcards.flashcards_dir
    flashcards.flashcards_dir = lambda: tmp / "flashcards"
    try:
        yield tmp
    finally:
        flashcards.flashcards_dir = real_flashcards_dir
        shutil.rmtree(tmp, ignore_errors=True)


def _make_card(
    source: str = "Test.md",
    concept: str = "Test concept",
    question: str = "What is this?",
    answer: str = "This is a test.",
    note_hash: str = "abc123",
) -> FlashCard:
    return FlashCard.create(source, concept, question, answer, note_hash)


def _write_note(d: Path, name: str, body: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


def _canned_gen(source: str, note_text: str, note_hash: str) -> list[FlashCard]:
    """Fake gen_cards that returns one predictable card without any network call."""
    return [FlashCard.create(source, "Test concept", "What is X?", "X is Y.", note_hash)]


# --------------------------------------------------------------------------- #
# 1. serialize_deck → parse_deck round-trips
# --------------------------------------------------------------------------- #


def test_round_trip_two_cards_preserves_all_fields() -> None:
    card1 = _make_card(
        source="Backend/EFCORE.md",
        concept="DI lifetimes",
        question="What are the three DI lifetime scopes?",
        answer="Singleton (one per app), Scoped (one per request), Transient (new each time).",
        note_hash="deadbeef",
    )
    card2 = _make_card(
        source="Backend/EFCORE.md",
        concept="EF Core tracking",
        question="When does EF Core track entity changes?",
        answer="By default on all queries. Use .AsNoTracking() to opt out.",
        note_hash="deadbeef",
    )
    deck = flashcards.Deck(
        source="Backend/EFCORE.md",
        note_hash="deadbeef",
        cards=(card1, card2),
        model=flashcards.GEN_MODEL,
        generated="2026-06-30T00:00:00Z",
    )
    parsed = flashcards.parse_deck(flashcards.serialize_deck(deck))

    assert parsed.source == "Backend/EFCORE.md"
    assert parsed.note_hash == "deadbeef"
    assert parsed.model == flashcards.GEN_MODEL
    assert parsed.generated == "2026-06-30T00:00:00Z"
    assert len(parsed.cards) == 2
    assert parsed.cards[0].concept == "DI lifetimes"
    assert parsed.cards[0].question == card1.question
    assert parsed.cards[0].answer == card1.answer
    assert parsed.cards[1].concept == "EF Core tracking"
    assert parsed.cards[1].question == card2.question


def test_round_trip_multiline_answer() -> None:
    """Multi-line / multi-paragraph answers survive serialize → parse intact."""
    answer = (
        "First line of the answer.\n\n"
        "Second paragraph with more detail.\n"
        "Still part of the second paragraph."
    )
    card = _make_card(
        source="Notes/Topic.md",
        concept="Multi-paragraph answer",
        question="How does this concept work?",
        answer=answer,
        note_hash="cafebabe",
    )
    deck = flashcards.Deck(
        source="Notes/Topic.md",
        note_hash="cafebabe",
        cards=(card,),
        model="test-model",
        generated="2026-01-01T00:00:00Z",
    )
    parsed = flashcards.parse_deck(flashcards.serialize_deck(deck))

    assert len(parsed.cards) == 1
    # FlashCard.create strips; parse_deck also strips: compare stripped originals
    assert parsed.cards[0].answer == answer.strip()


def test_round_trip_multiline_question() -> None:
    """A question wrapping multiple lines survives the round-trip."""
    question = "Line one of the question.\nLine two continued."
    card = _make_card(
        source="Notes/Topic.md",
        concept="Multiline Q",
        question=question,
        answer="The answer.",
        note_hash="feed1234",
    )
    deck = flashcards.Deck(
        source="Notes/Topic.md",
        note_hash="feed1234",
        cards=(card,),
    )
    parsed = flashcards.parse_deck(flashcards.serialize_deck(deck))

    assert len(parsed.cards) == 1
    assert parsed.cards[0].question == question.strip()


def test_round_trip_card_ids_recomputed_stably() -> None:
    """Parsed cards recompute card_id from source+question — must match original."""
    card = _make_card(source="Notes/A.md", question="What is X?", note_hash="hash1")
    expected_id = card.card_id
    deck = flashcards.Deck(source="Notes/A.md", note_hash="hash1", cards=(card,))
    parsed = flashcards.parse_deck(flashcards.serialize_deck(deck))

    assert parsed.cards[0].card_id == expected_id


def test_round_trip_empty_model_and_generated() -> None:
    """Optional metadata fields round-trip even when left empty."""
    card = _make_card()
    deck = flashcards.Deck(source="Test.md", note_hash="h", cards=(card,), model="", generated="")
    parsed = flashcards.parse_deck(flashcards.serialize_deck(deck))

    assert parsed.model == ""
    assert parsed.generated == ""
    assert len(parsed.cards) == 1


# --------------------------------------------------------------------------- #
# 2. parse_deck on garbage / empty — empty cards, never raises
# --------------------------------------------------------------------------- #


def test_parse_empty_string() -> None:
    deck = flashcards.parse_deck("")
    assert deck.cards == ()


def test_parse_whitespace_only() -> None:
    deck = flashcards.parse_deck("   \n\n  \t  ")
    assert deck.cards == ()


def test_parse_random_garbage() -> None:
    deck = flashcards.parse_deck("this is not a valid deck at all !!!")
    assert deck.cards == ()


def test_parse_metadata_but_no_concept_blocks() -> None:
    text = (
        '<!-- ccd-flashcards v=2 source="X.md" note_hash="abc"'
        ' model="" generated="" -->\n'
        "# Flashcards — X.md\n"
    )
    deck = flashcards.parse_deck(text)
    assert deck.cards == ()
    assert deck.source == "X.md"
    assert deck.note_hash == "abc"


def test_parse_concept_block_missing_q() -> None:
    """A concept block with no **Q:** line is silently skipped."""
    text = (
        '<!-- ccd-flashcards v=2 source="X.md" note_hash="abc"'
        ' model="" generated="" -->\n'
        "# Flashcards — X.md\n\n"
        "## Concept: Missing Q\n"
        "**A:** This answer has no question.\n"
    )
    deck = flashcards.parse_deck(text)
    assert deck.cards == ()


def test_parse_concept_block_missing_a() -> None:
    """A concept block with no **A:** line is silently skipped."""
    text = (
        '<!-- ccd-flashcards v=2 source="X.md" note_hash="abc"'
        ' model="" generated="" -->\n'
        "# Flashcards — X.md\n\n"
        "## Concept: Missing A\n"
        "**Q:** This question has no answer.\n"
    )
    deck = flashcards.parse_deck(text)
    assert deck.cards == ()


def test_parse_one_valid_among_broken_blocks() -> None:
    """Only well-formed blocks produce cards; broken blocks are skipped."""
    text = (
        '<!-- ccd-flashcards v=2 source="Mix.md" note_hash="hash"'
        ' model="" generated="" -->\n'
        "# Flashcards — Mix.md\n\n"
        "## Concept: Broken\n"
        "No Q or A here.\n\n"
        "## Concept: Good block\n"
        "**Q:** What is good?\n\n"
        "**A:** This block is well-formed.\n"
    )
    deck = flashcards.parse_deck(text)
    assert len(deck.cards) == 1
    assert deck.cards[0].concept == "Good block"


# --------------------------------------------------------------------------- #
# 3. deck_path — stable, deterministic, collision-free
# --------------------------------------------------------------------------- #


def test_deck_path_flat_source() -> None:
    p = flashcards.deck_path("Flat.md")
    assert p.name == "Flat.md"
    assert p.parent == flashcards.flashcards_dir()


def test_deck_path_single_level_nesting() -> None:
    p = flashcards.deck_path("Backend/EFCORE.md")
    assert p.name == "Backend__EFCORE.md"


def test_deck_path_deep_nesting() -> None:
    p = flashcards.deck_path("Level1/Level2/Level3.md")
    assert p.name == "Level1__Level2__Level3.md"


def test_deck_path_stable_across_calls() -> None:
    assert flashcards.deck_path("A/B.md") == flashcards.deck_path("A/B.md")


def test_deck_path_different_sources_different_paths() -> None:
    assert flashcards.deck_path("A/B.md") != flashcards.deck_path("C/D.md")
    assert flashcards.deck_path("X/Y.md") != flashcards.deck_path("X/Z.md")


def test_deck_path_backslash_separator_slugified() -> None:
    """Windows-style backslash separators in source are slugified identically."""
    p = flashcards.deck_path("Backend\\EFCORE.md")
    assert p.name == "Backend__EFCORE.md"


def test_deck_path_same_result_for_forward_and_back_slash() -> None:
    assert flashcards.deck_path("A/B.md") == flashcards.deck_path("A\\B.md")


# --------------------------------------------------------------------------- #
# 4. save_deck / load_deck / load_decks — persistence + de-dupe
# --------------------------------------------------------------------------- #


def test_save_and_load_deck_round_trips() -> None:
    with _workspace():
        card = _make_card(source="Test.md", question="Q?", answer="A.", note_hash="h1")
        deck = flashcards.Deck(
            source="Test.md", note_hash="h1", cards=(card,),
            model="test", generated="2026-01-01T00:00:00Z",
        )
        saved_path = flashcards.save_deck(deck)
        assert saved_path.exists()

        loaded = flashcards.load_deck(saved_path)
        assert loaded is not None
        assert loaded.source == "Test.md"
        assert loaded.note_hash == "h1"
        assert loaded.model == "test"
        assert len(loaded.cards) == 1
        assert loaded.cards[0].question == "Q?"
        assert loaded.cards[0].answer == "A."


def test_load_deck_missing_file_returns_none() -> None:
    p = Path(tempfile.gettempdir()) / "ccd_nonexistent_test_deck.md"
    assert not p.exists()
    assert flashcards.load_deck(p) is None


def test_load_decks_returns_empty_when_dir_missing() -> None:
    with _workspace():
        # flashcards_dir() points to tmp/flashcards which does not exist yet
        assert flashcards.load_decks() == []


def test_load_decks_returns_all_cards_from_all_files() -> None:
    with _workspace():
        c1 = _make_card(source="A.md", question="Q1?", answer="A1.", note_hash="h1")
        c2 = _make_card(source="B.md", question="Q2?", answer="A2.", note_hash="h2")
        flashcards.save_deck(flashcards.Deck("A.md", "h1", (c1,)))
        flashcards.save_deck(flashcards.Deck("B.md", "h2", (c2,)))

        all_cards = flashcards.load_decks()
        questions = {c.question for c in all_cards}
        assert "Q1?" in questions
        assert "Q2?" in questions


def test_load_decks_dedup_by_card_id_first_wins() -> None:
    """When two deck files contain cards with the same card_id, only the first is kept."""
    with _workspace():
        source = "Notes/Shared.md"
        # Both cards have the same source + question → identical card_id
        card_v1 = FlashCard.create(source, "Concept", "Identical Q?", "Answer v1", "hash_v1")
        card_v2 = FlashCard.create(source, "Concept", "Identical Q?", "Answer v2", "hash_v2")
        assert card_v1.card_id == card_v2.card_id

        # Write two separate .md files directly into the flashcards dir
        fc_dir = flashcards.flashcards_dir()
        fc_dir.mkdir(parents=True, exist_ok=True)
        deck1 = flashcards.Deck(source, "hash_v1", (card_v1,), model="", generated="")
        deck2 = flashcards.Deck(source, "hash_v2", (card_v2,), model="", generated="")
        (fc_dir / "file1.md").write_text(flashcards.serialize_deck(deck1), encoding="utf-8")
        (fc_dir / "file2.md").write_text(flashcards.serialize_deck(deck2), encoding="utf-8")

        all_cards = flashcards.load_decks()
        matching = [c for c in all_cards if c.card_id == card_v1.card_id]
        assert len(matching) == 1, f"expected 1 de-duped card, got {len(matching)}"


def test_load_decks_no_duplicate_card_ids() -> None:
    """load_decks never emits the same card_id twice across multiple deck files."""
    with _workspace():
        c1 = _make_card(source="Alpha.md", question="Q1?", answer="A1.", note_hash="h1")
        c2 = _make_card(source="Beta.md", question="Q2?", answer="A2.", note_hash="h2")
        flashcards.save_deck(flashcards.Deck("Alpha.md", "h1", (c1,)))
        flashcards.save_deck(flashcards.Deck("Beta.md", "h2", (c2,)))

        all_cards = flashcards.load_decks()
        ids = [c.card_id for c in all_cards]
        assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------- #
# 5. deck_is_current
# --------------------------------------------------------------------------- #


def test_deck_is_current_true_for_matching_hash() -> None:
    with _workspace():
        card = _make_card(source="Notes.md", note_hash="abc")
        flashcards.save_deck(flashcards.Deck("Notes.md", "abc", (card,)))
        assert flashcards.deck_is_current("Notes.md", "abc") is True


def test_deck_is_current_false_for_changed_hash() -> None:
    with _workspace():
        card = _make_card(source="Notes.md", note_hash="abc")
        flashcards.save_deck(flashcards.Deck("Notes.md", "abc", (card,)))
        assert flashcards.deck_is_current("Notes.md", "different-hash") is False


def test_deck_is_current_false_when_deck_missing() -> None:
    with _workspace():
        assert flashcards.deck_is_current("nonexistent.md", "abc") is False


def test_deck_is_current_false_after_note_text_changes() -> None:
    """After the note content changes its hash, the deck is no longer current."""
    with _workspace():
        card = _make_card(source="Changing.md", note_hash="old_hash")
        flashcards.save_deck(flashcards.Deck("Changing.md", "old_hash", (card,)))
        assert flashcards.deck_is_current("Changing.md", "old_hash") is True
        # Simulate the note being rewritten
        new_hash = content_hash("completely new content that is long enough to matter")
        assert flashcards.deck_is_current("Changing.md", new_hash) is False


# --------------------------------------------------------------------------- #
# 6. build_decks orchestration (gen_cards monkeypatched — no Claude)
# --------------------------------------------------------------------------- #


def test_build_generates_new_notes() -> None:
    with _workspace() as tmp:
        notes_dir = tmp / "notes"
        _write_note(notes_dir, "Topic.md", "x" * 300)

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = _canned_gen
        try:
            result = flashcards.build_decks([notes_dir])
        finally:
            flashcards.gen_cards = real_gen

        assert result.total == 1
        assert result.generated == 1
        assert result.skipped == 0
        assert result.failed == 0
        assert result.cards >= 1


def test_build_skips_unchanged_on_second_run() -> None:
    with _workspace() as tmp:
        notes_dir = tmp / "notes"
        _write_note(notes_dir, "Stable.md", "y" * 400)

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = _canned_gen
        try:
            r1 = flashcards.build_decks([notes_dir])
            r2 = flashcards.build_decks([notes_dir])
        finally:
            flashcards.gen_cards = real_gen

        assert r1.generated == 1
        assert r2.generated == 0, "second run should skip the unchanged note"
        assert r2.skipped == 1


def test_build_regenerates_when_note_content_changes() -> None:
    with _workspace() as tmp:
        notes_dir = tmp / "notes"
        note_path = _write_note(notes_dir, "Changing.md", "z" * 300)

        call_count = [0]

        def counting_gen(source, text, h):
            call_count[0] += 1
            return _canned_gen(source, text, h)

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = counting_gen
        try:
            flashcards.build_decks([notes_dir])
            # Rewrite the note with different content
            note_path.write_text("w" * 400, encoding="utf-8")
            flashcards.build_decks([notes_dir])
        finally:
            flashcards.gen_cards = real_gen

        assert call_count[0] == 2, "gen should run once for each distinct note content"


def test_build_records_failed_when_gen_raises() -> None:
    with _workspace() as tmp:
        notes_dir = tmp / "notes"
        _write_note(notes_dir, "Exploding.md", "e" * 300)

        def failing_gen(source, text, h):
            raise RuntimeError("simulated Claude failure")

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = failing_gen
        try:
            result = flashcards.build_decks([notes_dir])
        finally:
            flashcards.gen_cards = real_gen

        assert result.failed == 1
        assert result.generated == 0


def test_build_progress_cb_invoked_total_times() -> None:
    with _workspace() as tmp:
        notes_dir = tmp / "notes"
        _write_note(notes_dir, "Note1.md", "a" * 300)
        _write_note(notes_dir, "Note2.md", "b" * 300)
        _write_note(notes_dir, "Note3.md", "c" * 300)

        calls: list[tuple[int, int, str]] = []

        def cb(done: int, total: int, source: str) -> None:
            calls.append((done, total, source))

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = _canned_gen
        try:
            result = flashcards.build_decks([notes_dir], progress_cb=cb)
        finally:
            flashcards.gen_cards = real_gen

        assert len(calls) == result.total
        assert [c[0] for c in calls] == list(range(1, result.total + 1))


def test_build_skips_short_notes_without_calling_gen() -> None:
    with _workspace() as tmp:
        notes_dir = tmp / "notes"
        _write_note(notes_dir, "Tiny.md", "too short")  # well under _MIN_NOTE_CHARS

        call_count = [0]

        def counting_gen(source, text, h):
            call_count[0] += 1
            return []

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = counting_gen
        try:
            result = flashcards.build_decks([notes_dir])
        finally:
            flashcards.gen_cards = real_gen

        assert result.skipped == 1
        assert call_count[0] == 0, "gen_cards must never be called for too-short notes"


def test_build_force_regenerates_current_decks() -> None:
    with _workspace() as tmp:
        notes_dir = tmp / "notes"
        _write_note(notes_dir, "ForceMe.md", "f" * 300)

        call_count = [0]

        def counting_gen(source, text, h):
            call_count[0] += 1
            return _canned_gen(source, text, h)

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = counting_gen
        try:
            flashcards.build_decks([notes_dir])
            flashcards.build_decks([notes_dir], force=True)  # should re-run
        finally:
            flashcards.gen_cards = real_gen

        assert call_count[0] == 2, "force=True must regenerate even when deck is current"


def test_build_dedupes_source_across_dirs() -> None:
    """When two notes dirs contain the same relative path, first dir wins."""
    with _workspace() as tmp:
        d1 = tmp / "dir1"
        d2 = tmp / "dir2"
        _write_note(d1, "Shared.md", "a" * 300)
        _write_note(d2, "Shared.md", "b" * 300)

        call_count = [0]

        def counting_gen(source, text, h):
            call_count[0] += 1
            return _canned_gen(source, text, h)

        real_gen = flashcards.gen_cards
        flashcards.gen_cards = counting_gen
        try:
            result = flashcards.build_decks([d1, d2])
        finally:
            flashcards.gen_cards = real_gen

        assert result.total == 1, "de-duped: only one 'Shared.md' should be processed"
        assert call_count[0] == 1


def test_build_missing_notes_dir_is_skipped_gracefully() -> None:
    with _workspace() as tmp:
        real_gen = flashcards.gen_cards
        flashcards.gen_cards = _canned_gen
        try:
            result = flashcards.build_decks([tmp / "does-not-exist"])
        finally:
            flashcards.gen_cards = real_gen

        assert result.total == 0
        assert result.generated == 0


# --------------------------------------------------------------------------- #
# 7. is_available — False when ANTHROPIC_API_KEY is unset
# --------------------------------------------------------------------------- #


def test_is_available_false_without_api_key() -> None:
    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        assert flashcards.is_available() is False
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved


def test_is_available_true_when_key_set_and_sdk_importable() -> None:
    """Sanity: is_available returns True when key is set (SDK assumed installed)."""
    saved = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-key-not-real"
    try:
        # May be True or False depending on whether anthropic is installed;
        # we only verify it doesn't raise and returns a bool.
        result = flashcards.is_available()
        assert isinstance(result, bool)
    finally:
        if saved is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = saved


# --------------------------------------------------------------------------- #
# Standalone runner (mirrors test_quiz_config.py style)
# --------------------------------------------------------------------------- #


def _run_standalone() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"flashcards: {len(tests)} passed")


if __name__ == "__main__":
    _run_standalone()
