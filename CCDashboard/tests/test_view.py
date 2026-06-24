"""Light headless integration test for the CONVERSATIONS view.

A single ``@pytest.mark.integration`` test that mounts the real Textual app with an
*injected* in-memory index (no ``~/.claude`` filesystem dependency), types a query,
and asserts the table reorders to put the relevant chat on top and that the preview
pane updates with highlighted context. Per the spec this is intentionally minimal;
everything else is covered by the pure-engine unit tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import ccdashboard.tui.app as _app_module
from ccdashboard.tui.app import CCDashboardApp
from ccdashboard.tui.conversations_view import ConversationsView

pytestmark = pytest.mark.integration

# The view debounces search by ~180 ms; pause comfortably longer so the deferred
# search actually runs before we assert.
_DEBOUNCE_WAIT = 0.4

# ``CCDashboardApp.CSS_PATH = "app.tcss"`` is resolved by Textual relative to the
# module that *defines* the App subclass. Our subclass lives here in tests/, where no
# ``app.tcss`` exists, so pin the real stylesheet (next to app.py) by absolute path.
_APP_TCSS = str(Path(_app_module.__file__).resolve().parent / "app.tcss")


class _InjectedApp(CCDashboardApp):
    """App that skips the real filesystem index load and uses a supplied index.

    Overriding ``_load`` keeps the test hermetic: no ``~/.claude`` scan, no Claude
    calls, deterministic data. After mount we push the injected convos straight into
    the views the same way ``_populate`` would.
    """

    CSS_PATH = _APP_TCSS

    def __init__(self, config_dir: Path, convos: list) -> None:
        super().__init__(config_dir)
        self._injected_convos = convos

    def _load(self) -> None:  # type: ignore[override]
        # Replace the threaded indexer with a synchronous inject on the UI thread.
        self.query_one(ConversationsView).load_conversations(self._injected_convos)


def _titles(view: ConversationsView) -> list[str]:
    """Current display order of conversation titles (parallel to the table rows)."""
    return [c.title for c in view._ccd_rows]


def test_conversations_view_reorders_and_updates_preview(make_convo, tmp_path) -> None:
    """Type a query in the running app; the table reorders and the preview updates.

    Driven through Textual's ``Pilot``. The async body is run via ``asyncio.run`` so
    no ``pytest-asyncio`` plugin is required (the dev deps pin only ``pytest``).
    """
    import asyncio

    from textual.widgets import Static

    # A body-only 'grep' hit that is newest, and a title 'grep' hit that is older.
    # Plain newest-first would rank the body hit first; relevance ranking must float
    # the title hit to the top once we search.
    body_hit = make_convo(
        session_id="body0001-aaaa-bbbb-cccc-000000000001",
        title="Unrelated newest chat",
        text="somewhere in here we mention grep once",
        last_at="2026-06-24T12:00:00.000Z",
    )
    title_hit = make_convo(
        session_id="title001-aaaa-bbbb-cccc-000000000002",
        title="Grep pipeline deep dive",
        text="body without the keyword",
        last_at="2026-06-01T12:00:00.000Z",
    )
    convos = [body_hit, title_hit]  # newest-first order as the indexer would yield

    app = _InjectedApp(tmp_path, convos)

    async def _drive() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            # Land on the CONVERSATIONS tab.
            app.action_show("conversations")
            await pilot.pause()

            view = app.query_one(ConversationsView)

            # Before searching: pure newest-first order (body hit on top).
            assert _titles(view)[0] == "Unrelated newest chat"

            # Type a query into the search box. Focus it first, then send keystrokes.
            view.focus_search()
            await pilot.pause()
            await pilot.press("g", "r", "e", "p")
            # Wait out the debounce so the deferred search runs.
            await pilot.pause(_DEBOUNCE_WAIT)

            # The table reordered: title hit now outranks the newer body-only hit.
            assert _titles(view)[0] == "Grep pipeline deep dive"
            assert len(view._ccd_rows) == 2  # both still match (coverage holds)

            # The preview pane updated with content for the top (highlighted) row.
            # ``Static.render()`` returns the current renderable (a rich Text/Content
            # exposing ``.plain``); fall back to ``str`` for any other renderable type.
            preview = view.query_one("#conv-preview", Static)
            rendered = preview.render()
            preview_text = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            assert "Grep pipeline deep dive" in preview_text

    asyncio.run(_drive())


def test_conversations_view_has_spec_element_ids(make_convo, tmp_path) -> None:
    """Sanity check (non-Pilot): the view exposes the IDs the wiring/tests rely on.

    Run synchronously via run_test in a fresh loop to avoid requiring the asyncio
    plugin for this lightweight structural assertion.
    """
    import asyncio

    from textual.widgets import DataTable, Input, Select, Static

    convos = [make_convo(session_id="s1", title="Only chat")]
    app = _InjectedApp(tmp_path, convos)

    async def _check() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show("conversations")
            await pilot.pause()
            view = app.query_one(ConversationsView)
            # IDs defined by the spec's layout (Section 5.1).
            view.query_one("#conv-project", Select)
            view.query_one("#conv-date", Select)
            view.query_one("#conv-search", Input)
            view.query_one("#conv-table", DataTable)
            view.query_one("#conv-preview", Static)
            view.query_one("#conv-status", Static)

    asyncio.run(_check())
