"""Config tab — a searchable table of ~/.claude components (from scan.build_view_model)."""
from __future__ import annotations

from textual import events, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from ccdashboard import editor


class ConfigView(Vertical):
    """Search box + table of config components. ``_ccd_*`` avoids name clashes."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_items: list[dict] = []
        self._ccd_rows: list[dict] = []   # items currently shown (parallel to table rows)

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="search config…  (↓ then Enter to open the file in VS Code)",
            id="config-search",
        )
        yield DataTable(id="config-table", zebra_stripes=True, cursor_type="row")
        yield Static("loading…", id="config-status", classes="status")

    def on_mount(self) -> None:
        table = self.query_one("#config-table", DataTable)
        table.add_columns("KIND", "ID", "NAME", "ALWAYS", "INVOKE")

    def load_items(self, vm: dict) -> None:
        self._ccd_items = vm.get("items", [])
        self._ccd_render(self._ccd_items)
        total = vm.get("summary", {}).get("total", len(self._ccd_items))
        by = vm.get("summary", {}).get("by_kind", {})
        kinds = "  ".join(f"{k}:{v}" for k, v in by.items() if v)
        self.query_one("#config-status", Static).update(f"{total} components   ·   {kinds}")

    def _ccd_render(self, items: list[dict]) -> None:
        table = self.query_one("#config-table", DataTable)
        table.clear()
        self._ccd_rows = list(items)
        for it in items:
            always = it.get("tokens_always_loaded")
            invoke = it.get("tokens_invocation")
            table.add_row(
                it.get("kind", ""),
                it.get("id", ""),
                (it.get("name", "") or "")[:40],
                str(always) if always is not None else "—",
                str(invoke) if invoke is not None else "—",
            )

    def focus_search(self) -> None:
        """Put keyboard focus on the search box (the tab's entry point)."""
        self.query_one("#config-search", Input).focus()

    def on_key(self, event: events.Key) -> None:
        # Down-arrow from the search box drops focus into the results table.
        if event.key != "down" or self.app.focused is not self.query_one("#config-search", Input):
            return
        table = self.query_one("#config-table", DataTable)
        if table.row_count:
            table.focus()
            event.stop()
            event.prevent_default()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "config-search":
            return
        q = event.value.lower().strip()
        if not q:
            self._ccd_render(self._ccd_items)
            return
        matched = [
            it for it in self._ccd_items
            if q in (
                str(it.get("name", "")) + str(it.get("id", ""))
                + str(it.get("kind", "")) + str(it.get("description", ""))
            ).lower()
        ]
        self._ccd_render(matched)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Enter (or click) on a row opens that component's source file in an editor.
        if event.data_table.id != "config-table":
            return
        idx = event.cursor_row
        if 0 <= idx < len(self._ccd_rows):
            self._ccd_open(self._ccd_rows[idx])

    @work(thread=True)
    def _ccd_open(self, item: dict) -> None:
        name = item.get("name") or item.get("id") or "item"
        path = item.get("abs_path")
        if not path:
            self.app.call_from_thread(
                self.app.notify, f"No file on disk for “{name}”.",
                severity="warning", timeout=6,
            )
            return
        try:
            plan = editor.open_in_editor(path)
            where = "VS Code" if plan["editor"] == "vscode" else "the default editor"
            self.app.call_from_thread(
                self.app.notify, f"Opened “{name}” in {where}.", timeout=5
            )
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.app.notify, f"Open failed: {exc}", severity="error", timeout=8
            )
