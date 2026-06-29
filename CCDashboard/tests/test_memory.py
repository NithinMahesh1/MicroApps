"""Tests for the memory indexer, search-engine reuse, and MemoriesView.

Sections:
1. _parse_frontmatter  — internal YAML-ish parser for memory file frontmatter
2. _project_label      — readable project label from an encoded cwd slug
3. index_memories      — filesystem scanner + derived search-field contract
4. Search-engine reuse — Memory duck-types cleanly through search.rank/merge_ui_filters
5. split_type_operator — inline ``type:foo`` extraction from the search box text
6. preview             — reading-pane rich Text builder
7. Integration         — headless Textual Pilot test for MemoriesView
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from ccdashboard import memory, search
from ccdashboard.memory import Memory

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Local factory — mirrors conftest.make_convo, computes same derived fields
# as _parse_memory() so tests share the real indexer's field contract.
# ---------------------------------------------------------------------------


def _make_memory(
    *,
    name: str = "Test Memory",
    description: str = "A test description",
    type: str = "untyped",
    body: str = "",
    project_name: str = "MyGit-mock-project",
    project_slug: str = "mock-slug",
    file_path: str = "/fake/memory/test.md",
    last_at: str = "2026-06-24T10:00:00",
    modified: str = "2026-06-24 10:00",
    session_id: str | None = None,
) -> Memory:
    """Build a Memory with all derived fields computed, matching _parse_memory logic."""
    last_date: date | None = None
    try:
        last_date = date.fromisoformat(last_at[:10])
    except ValueError:
        pass
    # body_lc mirrors: f"{description}\n{body}".lower()
    searchable = f"{description}\n{body}".lower()
    filename = Path(file_path).name
    _session_id = session_id if session_id is not None else f"{project_slug}/{filename}"
    return Memory(
        name=name,
        description=description,
        type=type,
        body=body,
        project_name=project_name,
        project_slug=project_slug,
        file_path=file_path,
        modified=modified,
        title=name,
        title_lc=name.lower(),
        body_lc=searchable,
        project_lc=project_name.lower(),
        branch_lc="",
        last_at=last_at,
        last_date=last_date,
        session_id=_session_id,
    )


# ---------------------------------------------------------------------------
# 1. _parse_frontmatter
# ---------------------------------------------------------------------------


def test_parse_frontmatter_flat_type() -> None:
    """Shape A: top-level ``type:`` key is captured directly."""
    text = "---\nname: My Memory\ndescription: Flat desc\ntype: feedback\n---\nThe body"
    fields, body = memory._parse_frontmatter(text)
    assert fields["name"] == "My Memory"
    assert fields["description"] == "Flat desc"
    assert fields["type"] == "feedback"
    assert "The body" in body


def test_parse_frontmatter_nested_metadata_type() -> None:
    """Shape B: ``type:`` nested under a ``metadata:`` block is still captured."""
    text = (
        "---\n"
        "name: Nested\n"
        "description: Nested desc\n"
        "metadata:\n"
        "  node_type: memory\n"
        "  type: project\n"
        "---\n"
        "Nested body"
    )
    fields, body = memory._parse_frontmatter(text)
    assert fields.get("type") == "project"
    assert "Nested body" in body


def test_parse_frontmatter_node_type_not_mistaken_for_type() -> None:
    """``node_type:`` is metadata noise — must NOT be captured as the memory type."""
    text = (
        "---\n"
        "name: Test\n"
        "metadata:\n"
        "  node_type: memory\n"
        "---\n"
        "body"
    )
    fields, _ = memory._parse_frontmatter(text)
    assert "type" not in fields
    assert "node_type" not in fields


def test_parse_frontmatter_quoted_description_strips_double_quotes() -> None:
    text = '---\nname: Q\ndescription: "Quoted value here"\ntype: untyped\n---\nbody'
    fields, _ = memory._parse_frontmatter(text)
    assert fields["description"] == "Quoted value here"


def test_parse_frontmatter_quoted_description_strips_single_quotes() -> None:
    text = "---\nname: Q\ndescription: 'Single quoted'\n---\nbody"
    fields, _ = memory._parse_frontmatter(text)
    assert fields["description"] == "Single quoted"


def test_parse_frontmatter_no_frontmatter_returns_empty_dict_and_full_text() -> None:
    """A file with no opening ``---`` yields ({}, full-text) so it still surfaces."""
    text = "No frontmatter here\nJust a plain text file"
    fields, body = memory._parse_frontmatter(text)
    assert fields == {}
    assert body == text


def test_parse_frontmatter_unterminated_fence_returns_empty() -> None:
    """An opening ``---`` with no closing fence is treated as no frontmatter."""
    text = "---\nname: X\n(no closing fence)"
    fields, body = memory._parse_frontmatter(text)
    assert fields == {}
    assert body == text


# ---------------------------------------------------------------------------
# 2. _project_label
# ---------------------------------------------------------------------------


def _home_slug() -> str:
    """Encoded home slug as _encode_home() computes it — machine-independent."""
    return str(Path.home()).replace(":", "-").replace("\\", "-").replace("/", "-")


def test_project_label_strips_home_prefix_keeps_full_remainder() -> None:
    """The home prefix is removed; the full repo path remainder is kept intact."""
    slug = _home_slug() + "-MyGit-smart-gift-card"
    label = memory._project_label(slug)
    # The entire remainder must be kept — not just the final dash-segment.
    assert label == "MyGit-smart-gift-card"
    assert label != "card"   # naively splitting on '-' would give the wrong answer


def test_project_label_slug_equal_to_home_returns_home_leaf() -> None:
    """When the cwd IS the home dir, return its basename."""
    slug = _home_slug()
    label = memory._project_label(slug)
    assert label == Path.home().name


def test_project_label_non_home_slug_returned_as_is() -> None:
    """A cwd outside the user's home dir falls back to the raw slug."""
    slug = "opt-apps-myrepo"
    label = memory._project_label(slug)
    assert label == slug


def test_project_label_worktree_stays_distinct_from_main_checkout() -> None:
    """Same repo under a temp/worktree path produces a different label from main."""
    main_slug = _home_slug() + "-MyGit-smart-gift-card"
    worktree_slug = _home_slug() + "-temp-smart-gift-card-worktree"
    assert memory._project_label(main_slug) != memory._project_label(worktree_slug)


# ---------------------------------------------------------------------------
# 3. index_memories
# ---------------------------------------------------------------------------


def _write_memory_file(
    projects_dir: Path,
    *,
    slug: str,
    filename: str,
    content: str,
) -> Path:
    """Write a .md file under <projects_dir>/<slug>/memory/<filename>."""
    mem_dir = projects_dir / slug / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    path = mem_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_index_memories_skips_memory_md(tmp_path: Path) -> None:
    """MEMORY.md (the human-readable index) must be skipped, real files indexed."""
    slug = "C--test-project"
    _write_memory_file(tmp_path, slug=slug, filename="MEMORY.md", content="# Index\n- item")
    _write_memory_file(
        tmp_path,
        slug=slug,
        filename="real-memory.md",
        content="---\nname: Real\n---\nbody",
    )
    mems = memory.index_memories(tmp_path)
    assert len(mems) == 1
    assert mems[0].name == "Real"


def test_index_memories_newest_mtime_first(tmp_path: Path) -> None:
    """index_memories returns memories sorted newest-mtime-first."""
    slug = "C--test-ordering"
    older = _write_memory_file(
        tmp_path, slug=slug, filename="older.md",
        content="---\nname: Older Memory\n---\nold body",
    )
    newer = _write_memory_file(
        tmp_path, slug=slug, filename="newer.md",
        content="---\nname: Newer Memory\n---\nnew body",
    )
    # Pin mtimes to deterministic timestamps so CI never flakes on filesystem timing.
    ts_old = 1_698_000_000
    ts_new = 1_700_000_000
    os.utime(older, (ts_old, ts_old))
    os.utime(newer, (ts_new, ts_new))

    mems = memory.index_memories(tmp_path)
    assert mems[0].name == "Newer Memory"
    assert mems[1].name == "Older Memory"


def test_index_memories_no_frontmatter_defaults_to_untyped(tmp_path: Path) -> None:
    """A .md with no frontmatter is still indexed with type='untyped'."""
    slug = "C--test-untyped"
    _write_memory_file(
        tmp_path,
        slug=slug,
        filename="bare.md",
        content="No frontmatter, just plain text as a memory body.",
    )
    mems = memory.index_memories(tmp_path)
    assert len(mems) == 1
    assert mems[0].type == "untyped"


def test_index_memories_derived_search_fields_populated(tmp_path: Path) -> None:
    """index_memories populates title_lc, body_lc, project_lc, and session_id correctly."""
    slug = "C--test-fields"
    filename = "my-memory.md"
    content = (
        "---\n"
        "name: My Test Memory\n"
        "description: Searchable description here\n"
        "type: project\n"
        "---\n"
        "This is the body text."
    )
    _write_memory_file(tmp_path, slug=slug, filename=filename, content=content)

    mems = memory.index_memories(tmp_path)
    assert len(mems) == 1
    m = mems[0]

    # title / title_lc mirror the name
    assert m.title == "My Test Memory"
    assert m.title_lc == "my test memory"

    # body_lc is description + body, lowercased
    assert "searchable description here" in m.body_lc
    assert "this is the body text." in m.body_lc

    # project_lc is project_name lowercased
    assert m.project_lc == m.project_name.lower()

    # session_id uniquely identifies the file within the index
    assert m.session_id == f"{slug}/{filename}"

    # last_date is a real date object
    assert m.last_date is not None
    assert isinstance(m.last_date, date)


# ---------------------------------------------------------------------------
# 4. Search-engine reuse
# ---------------------------------------------------------------------------


def test_search_rank_floats_title_hit_above_body_only_hit() -> None:
    """search.rank works on Memory records: a name/title hit outranks a body-only hit.

    The title hit is older (lower recency) so plain browse order would put the body
    hit first; relevance ranking must flip them — proving the engine's _W_TITLE
    dominance holds for Memory the same way it does for Conversation.
    """
    title_hit = _make_memory(
        name="Foo pipeline deep dive",
        description="something unrelated",
        body="nothing here",
        project_name="MyGit-project-a",
        project_slug="slug-a",
        file_path="/fake/memory/title.md",
        last_at="2026-06-01T10:00:00",  # older
    )
    body_hit = _make_memory(
        name="Unrelated Memory",
        description="foo is mentioned here in the description",
        body="more foo content",
        project_name="MyGit-project-a",
        project_slug="slug-a",
        file_path="/fake/memory/body.md",
        last_at="2026-06-24T12:00:00",  # newer
    )
    ranked = search.rank([body_hit, title_hit], search.parse_query("foo"))
    assert ranked[0].name == "Foo pipeline deep dive"


def test_search_rank_project_filter_on_memory() -> None:
    """search.merge_ui_filters + rank filters Memory by project_lc unchanged."""
    project_a = _make_memory(
        name="Memory A",
        project_name="MyGit-project-alpha",
        project_slug="slug-alpha",
        file_path="/fake/memory/a.md",
        last_at="2026-06-24T10:00:00",
    )
    project_b = _make_memory(
        name="Memory B",
        project_name="MyGit-project-beta",
        project_slug="slug-beta",
        file_path="/fake/memory/b.md",
        last_at="2026-06-24T10:00:00",
    )
    q = search.merge_ui_filters(
        search.parse_query(""), project="MyGit-project-alpha"
    )
    ranked = search.rank([project_a, project_b], q)
    assert len(ranked) == 1
    assert ranked[0].name == "Memory A"


# ---------------------------------------------------------------------------
# 5. split_type_operator
# ---------------------------------------------------------------------------


def test_split_type_operator_extracts_type_token() -> None:
    cleaned, type_val = memory.split_type_operator("audit type:project foo")
    assert cleaned == "audit foo"
    assert type_val == "project"


def test_split_type_operator_no_type_token_returns_none() -> None:
    text = "just some keywords"
    cleaned, type_val = memory.split_type_operator(text)
    assert type_val is None
    assert cleaned == text


def test_split_type_operator_last_token_wins_when_two_present() -> None:
    """When two type: tokens appear, the last one wins."""
    _, type_val = memory.split_type_operator("type:feedback something type:project")
    assert type_val == "project"


def test_split_type_operator_type_key_is_case_insensitive() -> None:
    _, type_val = memory.split_type_operator("TYPE:Feedback notes")
    assert type_val == "feedback"


# ---------------------------------------------------------------------------
# 6. preview
# ---------------------------------------------------------------------------


def test_preview_plain_contains_name_and_body() -> None:
    """preview().plain must include the memory name and body text."""
    mem = _make_memory(name="My Special Memory", body="The body of this memory")
    result = memory.preview(mem)
    plain = result.plain
    assert "My Special Memory" in plain
    assert "The body of this memory" in plain


def test_preview_with_query_matched_term_appears_in_plain() -> None:
    """With a matching query, the matched term is present in the rendered plain text."""
    mem = _make_memory(
        name="Banana Facts",
        description="some intro",
        body="bananas are yellow and tasty",
    )
    q = search.parse_query("banana")
    result = memory.preview(mem, q)
    assert "banana" in result.plain.lower()


def test_preview_returns_rich_text_instance() -> None:
    from rich.text import Text

    mem = _make_memory(name="Test", body="body text")
    result = memory.preview(mem)
    assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# 7. Integration — headless Textual Pilot
# ---------------------------------------------------------------------------

import ccdashboard.tui.app as _app_module
from ccdashboard.tui.app import CCDashboardApp
from ccdashboard.tui.memory_view import MemoriesView

# Pin the real stylesheet path (next to app.py); our subclass lives in tests/
# where there is no app.tcss, so Textual can't find it via the default relative lookup.
_APP_TCSS = str(Path(_app_module.__file__).resolve().parent / "app.tcss")

# The view debounces search by ~180 ms; pause comfortably longer so the deferred
# search actually fires before assertions.
_DEBOUNCE_WAIT = 0.4


class _InjectedMemApp(CCDashboardApp):
    """App that skips the real filesystem index load and uses supplied Memory records.

    Overriding ``_load`` keeps the test hermetic: no ``~/.claude`` scan, no I/O,
    deterministic data. After mount we push the injected memories directly into the
    MemoriesView — the same call ``_populate`` would make.
    """

    CSS_PATH = _APP_TCSS

    def __init__(self, config_dir: Path, mems: list) -> None:
        super().__init__(config_dir)
        self._injected_mems = mems

    def _load(self) -> None:  # type: ignore[override]
        # Synchronous inject on the UI thread replaces the threaded worker.
        self.query_one(MemoriesView).load_memories(self._injected_mems)


def _mem_names(view: MemoriesView) -> list[str]:
    """Current display order of memory names (parallel to the table rows)."""
    return [m.name for m in view._ccd_rows]


@pytest.mark.integration
def test_memories_view_reorders_and_updates_preview(tmp_path: Path) -> None:
    """Type a query; table reorders with title hit first; preview shows that memory.

    The body_hit is newest so plain browse order puts it first.  After searching
    "foo", relevance ranking must float the title_hit to the top and the preview
    pane must reflect that — proving the debounced search + preview wiring work.
    """
    import asyncio

    from textual.widgets import Static

    body_hit = _make_memory(
        name="Unrelated Memory",
        description="foo is mentioned here",
        body="more foo content",
        project_name="MyGit-test-project",
        project_slug="test-slug",
        file_path="/fake/memory/body.md",
        last_at="2026-06-24T12:00:00",  # newest
    )
    title_hit = _make_memory(
        name="Foo pipeline deep dive",
        description="unrelated description",
        body="nothing keyword here",
        project_name="MyGit-test-project",
        project_slug="test-slug",
        file_path="/fake/memory/title.md",
        last_at="2026-06-01T10:00:00",  # older
    )
    mems = [body_hit, title_hit]  # injected order: newest-first (body hit on top)

    app = _InjectedMemApp(tmp_path, mems)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            # Switch to the MEMORIES tab.
            app.action_show("memories")
            await pilot.pause()

            view = app.query_one(MemoriesView)

            # Before searching: injected order — body_hit is first.
            assert _mem_names(view)[0] == "Unrelated Memory"

            # Focus the search box, type the query, wait out the debounce.
            view.focus_search()
            await pilot.pause()
            await pilot.press("f", "o", "o")
            await pilot.pause(_DEBOUNCE_WAIT)

            # Relevance ranking: title hit outranks the newer body-only hit.
            assert _mem_names(view)[0] == "Foo pipeline deep dive"
            assert len(view._ccd_rows) == 2  # both still match (coverage holds)

            # Preview pane updated to show the top-ranked memory's name.
            preview = view.query_one("#mem-preview", Static)
            rendered = preview.render()
            preview_text = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            assert "Foo pipeline deep dive" in preview_text

    asyncio.run(_drive())


@pytest.mark.integration
def test_memories_view_has_spec_element_ids(tmp_path: Path) -> None:
    """Non-Pilot structural check: all 7 spec element IDs are present on MemoriesView."""
    import asyncio

    from textual.widgets import DataTable, Input, Select, Static

    mems = [_make_memory(name="Singleton Memory")]
    app = _InjectedMemApp(tmp_path, mems)

    async def _check() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show("memories")
            await pilot.pause()
            view = app.query_one(MemoriesView)
            # Verify every element ID specified in the design:
            view.query_one("#mem-project", Select)
            view.query_one("#mem-type", Select)
            view.query_one("#mem-date", Select)
            view.query_one("#mem-search", Input)
            view.query_one("#mem-table", DataTable)
            view.query_one("#mem-preview", Static)
            view.query_one("#mem-status", Static)

    asyncio.run(_check())
