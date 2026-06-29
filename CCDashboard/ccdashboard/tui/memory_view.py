"""MEMORIES tab — search your Claude auto-memories; Enter on a row opens it in VS Code.

Structurally a sibling of the CONVERSATIONS view: the same debounced search box and
Project/Date dropdowns (reusing the shared :mod:`ccdashboard.search` engine verbatim),
plus a memory-only **Type** facet applied as a pre-filter so the shared engine is never
touched. Layout is list-beside-reading-pane — memories are short-form prose meant to be
read in full, so the right pane renders the whole selected memory (``memory.preview``)
instead of transcript-style snippets.
"""
from __future__ import annotations

from functools import partial

from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import DataTable, Input, Select, Static

from ccdashboard import editor, memory, search

# Same debounce the CONVERSATIONS view uses: cancel-and-reschedule a one-shot timer so a
# burst of keystrokes collapses into a single search. ~180 ms feels instant.
_SEARCH_DEBOUNCE_SECONDS = 0.18

# Date dropdown presets: (label, since_days). 0 means "Any time" (no after: filter).
_DATE_PRESETS: tuple[tuple[str, int], ...] = (
    ("Any time", 0),
    ("Last 24 hours", 1),
    ("Last 7 days", 7),
    ("Last 30 days", 30),
    ("Last year", 365),
)


class MemoriesView(Vertical):
    """Filters + search box + list/reading-pane of memories. Enter -> open in VS Code."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_memories: list = []   # full index
        self._ccd_rows: list = []       # currently displayed (parallel to table rows)
        self._ccd_search_timer: Timer | None = None   # pending debounced search, if any
        self._ccd_query: search.Query = search.Query()  # current effective query

    def compose(self) -> ComposeResult:
        with Horizontal(id="mem-filters", classes="filter-row"):
            yield Select(options=(), prompt="All projects", id="mem-project", allow_blank=True)
            yield Select(options=(), prompt="All types", id="mem-type", allow_blank=True)
            yield Select(options=_DATE_PRESETS, prompt="Any time", id="mem-date", allow_blank=True)
        yield Input(
            placeholder='search memories…  project:foo  type:feedback  after:2026-06-01  "phrase"',
            id="mem-search",
        )
        with Horizontal(id="mem-body"):
            yield DataTable(id="mem-table", zebra_stripes=True, cursor_type="row")
            yield Static("", id="mem-preview", classes="preview")
        yield Static("loading…", id="mem-status", classes="status")

    def on_mount(self) -> None:
        table = self.query_one("#mem-table", DataTable)
        table.add_columns("PROJECT", "TYPE", "NAME", "DESCRIPTION")

    def load_memories(self, memories: list) -> None:
        self._ccd_memories = memories
        self._populate_project_options(memories)
        self._populate_type_options(memories)
        self._ccd_render(memories)
        self.query_one("#mem-status", Static).update(
            f"{len(memories)} memories   ·   Enter on a row to open it in VS Code"
        )

    def _populate_project_options(self, memories: list) -> None:
        """Distinct project labels for the project dropdown (label == value, sorted)."""
        names = sorted({m.project_name for m in memories if m.project_name}, key=str.lower)
        self.query_one("#mem-project", Select).set_options((n, n) for n in names)

    def _populate_type_options(self, memories: list) -> None:
        """Distinct memory types for the type dropdown (derived from data, not hardcoded)."""
        types = sorted({m.type for m in memories if m.type})
        self.query_one("#mem-type", Select).set_options((t, t) for t in types)

    def _ccd_render(self, memories: list, query: search.Query | None = None) -> None:
        table = self.query_one("#mem-table", DataTable)
        table.clear()
        self._ccd_rows = list(memories)
        highlight = query is not None and not query.is_empty
        for m in memories:
            name_cell = search.highlight_title(m, query) if highlight else (m.name or "")[:40]
            table.add_row(
                (m.project_name or "")[:24],
                (m.type or "")[:10],
                name_cell,
                (m.description or "")[:60],
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "mem-search":
            return
        # Cancel any pending search and reschedule; only the last keystroke in a burst
        # actually runs the search. Timer.stop() is sync + idempotent.
        if self._ccd_search_timer is not None:
            self._ccd_search_timer.stop()
        self._ccd_search_timer = self.set_timer(
            _SEARCH_DEBOUNCE_SECONDS,
            partial(self._ccd_run_search, event.value.strip()),
            name="mem-search-debounce",
        )

    def on_select_changed(self, event: Select.Changed) -> None:
        # Project/type/date dropdowns re-run the search immediately (no debounce needed).
        if event.select.id not in ("mem-project", "mem-type", "mem-date"):
            return
        self._ccd_run_search(self._search_text())

    def _search_text(self) -> str:
        return self.query_one("#mem-search", Input).value.strip()

    def _select_value(self, select_id: str) -> object | None:
        """Return the chosen Select value, or None when nothing is selected.

        A blank ``Select`` (``allow_blank=True``) reports its value as the
        ``Select.NULL`` ``NoSelection`` sentinel; ``Select.is_blank()`` is the reliable
        way to detect it (matching how the CONVERSATIONS view reads its dropdowns).
        """
        select = self.query_one(select_id, Select)
        return None if select.is_blank() else select.value

    def _ccd_run_search(self, text: str) -> None:
        """Deferred search body (runs on the UI thread after the debounce window).

        Reuses the shared engine for free-text + project/date filters, then applies the
        memory-only Type facet as a plain pre-filter (dropdown or inline ``type:``) so
        ``search`` never has to know about memory types.
        """
        self._ccd_search_timer = None  # this run consumes the pending timer
        status = self.query_one("#mem-status", Static)

        cleaned, inline_type = memory.split_type_operator(text)
        q = search.parse_query(cleaned)
        q = search.merge_ui_filters(
            q,
            project=self._select_value("#mem-project"),
            since_days=self._select_value("#mem-date"),
        )
        self._ccd_query = q

        type_filter = inline_type or self._select_value("#mem-type")
        candidates = self._ccd_memories
        if type_filter:
            wanted = str(type_filter).lower()
            candidates = [m for m in candidates if m.type == wanted]

        ranked = search.rank(candidates, q)
        self._ccd_render(ranked, q)
        self._update_preview(0)

        if q.is_empty and not type_filter:
            status.update(f"{len(ranked)} memories")
        else:
            label = text.strip() or (f"type:{type_filter}" if type_filter else q.raw)
            status.update(
                f"{len(ranked)} match"
                + ("" if len(ranked) == 1 else "es")
                + f" for “{label}”"
            )

    def _update_preview(self, row: int) -> None:
        """Render the reading pane for the row at ``row`` (no-op when out of range)."""
        preview = self.query_one("#mem-preview", Static)
        if 0 <= row < len(self._ccd_rows):
            preview.update(memory.preview(self._ccd_rows[row], self._ccd_query))
        else:
            preview.update("")

    def focus_search(self) -> None:
        """Put keyboard focus on the search box (the tab's entry point)."""
        self.query_one("#mem-search", Input).focus()

    def on_key(self, event: events.Key) -> None:
        # Down-arrow from the search box drops focus into the results table.
        if event.key != "down" or self.app.focused is not self.query_one("#mem-search", Input):
            return
        table = self.query_one("#mem-table", DataTable)
        if table.row_count:
            table.focus()
            event.stop()
            event.prevent_default()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "mem-table":
            return
        self._update_preview(event.cursor_row)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "mem-table":
            return
        idx = event.cursor_row
        if 0 <= idx < len(self._ccd_rows):
            self._ccd_open(self._ccd_rows[idx])

    @work(thread=True)
    def _ccd_open(self, mem) -> None:
        """Open the memory's .md file in VS Code (OS-default fallback), off the UI thread."""
        try:
            plan = editor.open_in_editor(mem.file_path)
            where = "VS Code" if plan["editor"] == "vscode" else "the default editor"
            self.app.call_from_thread(
                self.app.notify, f"Opened “{mem.name}” in {where}.", timeout=5
            )
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.app.notify, f"Open failed: {exc}", severity="error", timeout=8
            )
