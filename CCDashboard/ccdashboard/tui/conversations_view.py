"""Conversations tab — search transcripts; Enter on a row resumes it (admin PowerShell)."""
from __future__ import annotations

from pathlib import Path

from textual import events, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from ccdashboard import conversations


class ConversationsView(Vertical):
    """Search box + table of conversations. Row select -> elevated ``claude --resume``."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_convos: list = []   # full index
        self._ccd_rows: list = []     # currently displayed (parallel to table rows)

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
        query = event.value.strip()
        if not query:
            self._ccd_render(self._ccd_convos)
            self.query_one("#conv-status", Static).update(f"{len(self._ccd_convos)} conversations")
            return
        ids = {r["session_id"] for r in conversations.search(self._ccd_convos, query)}
        matched = [c for c in self._ccd_convos if c.session_id in ids]
        self._ccd_render(matched)
        self.query_one("#conv-status", Static).update(
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
        try:
            conversations.launch_resume(convo.session_id, self._ccd_convos)
            self.app.call_from_thread(
                self.app.notify,
                f"Resuming “{convo.title[:40]}” — accept the UAC prompt.",
                timeout=8,
            )
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.app.notify, f"Resume failed: {exc}", severity="error", timeout=8
            )
