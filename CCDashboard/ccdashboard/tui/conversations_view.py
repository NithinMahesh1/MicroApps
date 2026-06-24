"""Conversations tab — search transcripts; Enter on a row resumes it (admin PowerShell)."""
from __future__ import annotations

from functools import partial
from pathlib import Path

from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Input, Select, Static

from ccdashboard import conversations, search

# No built-in debounce exists in Textual 8.2.x; we cancel-and-reschedule a one-shot
# timer so a burst of keystrokes collapses into a single search. ~180 ms feels instant.
_SEARCH_DEBOUNCE_SECONDS = 0.18

# Date dropdown presets: (label, since_days). 0 means "Any time" (no after: filter).
_DATE_PRESETS: tuple[tuple[str, int], ...] = (
    ("Any time", 0),
    ("Last 24 hours", 1),
    ("Last 7 days", 7),
    ("Last 30 days", 30),
    ("Last year", 365),
)


class ConversationsView(Vertical):
    """Search box + table of conversations. Row select -> elevated ``claude --resume``."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_convos: list = []   # full index
        self._ccd_rows: list = []     # currently displayed (parallel to table rows)
        self._ccd_search_timer: Timer | None = None  # pending debounced search, if any
        self._ccd_query: search.Query = search.Query()  # current effective query

    def compose(self) -> ComposeResult:
        with Horizontal(id="conv-filters", classes="filter-row"):
            yield Select(
                options=(),
                prompt="All projects",
                id="conv-project",
                allow_blank=True,
            )
            yield Select(
                options=_DATE_PRESETS,
                prompt="Any time",
                id="conv-date",
                allow_blank=True,
            )
        yield Input(
            placeholder='search…  project:foo  branch:bar  after:2026-06-01  "exact phrase"',
            id="conv-search",
        )
        yield DataTable(id="conv-table", zebra_stripes=True, cursor_type="row")
        yield Static(id="conv-preview", classes="preview")
        yield Static("loading…", id="conv-status", classes="status")

    def on_mount(self) -> None:
        table = self.query_one("#conv-table", DataTable)
        table.add_columns("BRANCH", "DIR", "MSGS", "LAST ACTIVE", "TITLE")

    def load_conversations(self, convos: list) -> None:
        self._ccd_convos = convos
        self._populate_project_options(convos)
        self._ccd_render(convos)
        self.query_one("#conv-status", Static).update(
            f"{len(convos)} conversations   ·   Enter on a row to resume in an elevated PowerShell"
        )

    def _populate_project_options(self, convos: list) -> None:
        """Set the project dropdown from distinct cwds (label=leaf, value=full cwd, by label)."""
        by_cwd: dict[str, str] = {}
        for c in convos:
            if c.cwd and c.cwd not in by_cwd:
                by_cwd[c.cwd] = c.project_name or Path(c.cwd).name
        options = sorted(
            ((label, cwd) for cwd, label in by_cwd.items()),
            key=lambda item: item[0].lower(),
        )
        self.query_one("#conv-project", Select).set_options(options)

    def _ccd_render(self, convos: list, query: search.Query | None = None) -> None:
        table = self.query_one("#conv-table", DataTable)
        table.clear()
        self._ccd_rows = list(convos)
        highlight = query is not None and not query.is_empty
        for c in convos:
            title_cell = (
                search.highlight_title(c, query) if highlight else (c.title or "")[:48]
            )
            table.add_row(
                (c.git_branch or "—")[:22],
                Path(c.cwd).name[:20],
                str(c.message_count),
                (c.last_at or "")[:16],
                title_cell,
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "conv-search":
            return
        # Cancel any pending search and reschedule; only the last keystroke in a
        # burst actually runs the search. Timer.stop() is sync + idempotent.
        if self._ccd_search_timer is not None:
            self._ccd_search_timer.stop()
        self._ccd_search_timer = self.set_timer(
            _SEARCH_DEBOUNCE_SECONDS,
            partial(self._ccd_run_search, event.value.strip()),
            name="conv-search-debounce",
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        # Project/date dropdowns re-run the search immediately (no debounce needed).
        if event.select.id not in ("conv-project", "conv-date"):
            return
        self._ccd_run_search(self._search_text())

    def _search_text(self) -> str:
        return self.query_one("#conv-search", Input).value.strip()

    def _select_value(self, select_id: str) -> object | None:
        """Return the chosen Select value, or None when nothing is selected.

        A blank ``Select`` (``allow_blank=True``) reports its value as the
        ``Select.NULL`` ``NoSelection`` sentinel — NOT ``Select.BLANK`` (which is the
        bool ``False`` in Textual 8.2.x). Use ``Select.is_blank()`` so a ``NoSelection``
        never leaks into ``search.merge_ui_filters`` (which would crash on ``.lower()``).
        """
        select = self.query_one(select_id, Select)
        return None if select.is_blank() else select.value

    def _ccd_run_search(self, text: str) -> None:
        """Deferred search body (runs on the UI thread after the debounce window).

        Scheduled via ``set_timer`` so widget updates here are safe without
        ``call_from_thread`` (that is only for ``@work(thread=True)`` workers).
        """
        self._ccd_search_timer = None  # this run consumes the pending timer
        status = self.query_one("#conv-status", Static)

        q = search.parse_query(text)
        q = search.merge_ui_filters(
            q,
            project=self._select_value("#conv-project"),
            since_days=self._select_value("#conv-date"),
        )
        self._ccd_query = q

        ranked = search.rank(self._ccd_convos, q)
        self._ccd_render(ranked, q)
        self._update_preview(0)

        if q.is_empty:
            status.update(f"{len(ranked)} conversations")
        else:
            label = text or q.raw
            status.update(
                f"{len(ranked)} match"
                + ("" if len(ranked) == 1 else "es")
                + f" for “{label}”"
            )

    def _update_preview(self, row: int) -> None:
        """Render the preview pane for the row at ``row`` (no-op when out of range)."""
        preview = self.query_one("#conv-preview", Static)
        if 0 <= row < len(self._ccd_rows):
            preview.update(search.highlight(self._ccd_rows[row], self._ccd_query))
        else:
            preview.update("")

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

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "conv-table":
            return
        self._update_preview(event.cursor_row)

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
