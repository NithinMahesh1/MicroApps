"""Conversations tab — search transcripts; Enter on a row resumes it (admin PowerShell)."""
from __future__ import annotations

from functools import partial
from pathlib import Path

from textual import events, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Input, Static

from ccdashboard import conversations

# No built-in debounce exists in Textual 8.2.x; we cancel-and-reschedule a one-shot
# timer so a burst of keystrokes collapses into a single search. ~180 ms feels instant.
_SEARCH_DEBOUNCE_SECONDS = 0.18


class ConversationsView(Vertical):
    """Search box + table of conversations. Row select -> elevated ``claude --resume``."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_convos: list = []   # full index
        self._ccd_rows: list = []     # currently displayed (parallel to table rows)
        self._ccd_search_timer: Timer | None = None  # pending debounced search, if any

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="search conversations…  (↓ to results, Enter to resume as admin)",
            id="conv-search",
        )
        yield DataTable(id="conv-table", zebra_stripes=True, cursor_type="row")
        yield Static("loading…", id="conv-status", classes="status")

    def on_mount(self) -> None:
        table = self.query_one("#conv-table", DataTable)
        table.add_columns("BRANCH", "DIR", "MSGS", "LAST ACTIVE", "TITLE")

    def load_conversations(self, convos: list) -> None:
        self._ccd_convos = convos
        self._ccd_render(convos)
        self.query_one("#conv-status", Static).update(
            f"{len(convos)} conversations   ·   Enter on a row to resume in an elevated PowerShell"
        )

    def _ccd_render(self, convos: list) -> None:
        table = self.query_one("#conv-table", DataTable)
        table.clear()
        self._ccd_rows = list(convos)
        for c in convos:
            table.add_row(
                (c.git_branch or "—")[:22],
                Path(c.cwd).name[:20],
                str(c.message_count),
                (c.last_at or "")[:16],
                (c.title or "")[:48],
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "conv-search":
            return
        # Cancel any pending search and reschedule; only the last keystroke in a
        # burst actually runs conversations.search. Timer.stop() is sync + idempotent.
        if self._ccd_search_timer is not None:
            self._ccd_search_timer.stop()
        self._ccd_search_timer = self.set_timer(
            _SEARCH_DEBOUNCE_SECONDS,
            partial(self._ccd_run_search, event.value.strip()),
            name="conv-search-debounce",
        )

    def _ccd_run_search(self, query: str) -> None:
        """Deferred search body (runs on the UI thread after the debounce window).

        Scheduled via ``set_timer`` so widget updates here are safe without
        ``call_from_thread`` (that is only for ``@work(thread=True)`` workers).
        """
        self._ccd_search_timer = None  # this run consumes the pending timer
        status = self.query_one("#conv-status", Static)
        if not query:
            self._ccd_render(self._ccd_convos)
            status.update(f"{len(self._ccd_convos)} conversations")
            return
        matched = conversations.filter_conversations(self._ccd_convos, query)
        self._ccd_render(matched)
        status.update(
            f"{len(matched)} match" + ("" if len(matched) == 1 else "es") + f" for “{query}”"
        )

    def focus_search(self) -> None:
        """Put keyboard focus on the search box (the tab's entry point)."""
        self.query_one("#conv-search", Input).focus()

    def on_key(self, event: events.Key) -> None:
        # Down-arrow from the search box drops focus into the results table.
        if event.key != "down" or self.app.focused is not self.query_one("#conv-search", Input):
            return
        table = self.query_one("#conv-table", DataTable)
        if table.row_count:
            table.focus()
            event.stop()
            event.prevent_default()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "conv-table":
            return
        idx = event.cursor_row
        if 0 <= idx < len(self._ccd_rows):
            self._resume(self._ccd_rows[idx])

    @work(thread=True)
    def _resume(self, convo) -> None:
        title = (convo.title or "")[:34]
        try:
            # Notify first — once the Win key fires, Start (then the admin window)
            # covers the TUI, so the paste reminder needs to be on screen already.
            self.app.call_from_thread(
                self.app.notify,
                f"Opening admin PowerShell for “{title}” — approve UAC, then press "
                "Ctrl+V, Enter (the resume command is on your clipboard).",
                timeout=12,
            )
            conversations.launch_resume(convo.session_id, self._ccd_convos)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.app.notify, f"Resume failed: {exc}", severity="error", timeout=8
            )
