"""Modal to view / add / remove the QuizMe study-notes folders.

"Add folder…" opens the OS-native picker (:mod:`ccdashboard.folder_picker`) in a
worker thread so the UI stays responsive; a typed/pasted path is also accepted
as a fallback when no native picker is installed. **Save** persists the list via
``quiz.save_notes_dirs`` and dismisses ``True`` so the caller can reload cards;
**Cancel** dismisses ``False``. ``_ccd_`` prefixes avoid Textual-internal clashes.
"""
from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from ccdashboard import folder_picker, quiz


class NotesConfigScreen(ModalScreen[bool]):
    """Choose the folder(s) QuizMe reads Markdown notes from."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    NotesConfigScreen { align: center middle; }
    #notes-dialog {
        width: 84; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 1 2;
    }
    #notes-dialog .title {
        width: 100%; content-align: center middle; text-style: bold; color: $accent;
    }
    #notes-dialog .hint { color: $text-muted; margin-bottom: 1; }
    #notes-list { height: 9; border: round $primary; margin-bottom: 1; }
    #notes-add-row { height: 3; margin-bottom: 1; }
    #notes-path { width: 1fr; }
    #notes-add-row Button { margin-left: 1; }
    #notes-btns { height: 3; align: center middle; }
    #notes-btns Button { margin: 0 1; }
    """

    def __init__(self, dirs: list[Path] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_dirs: list[Path] = list(dirs if dirs is not None else quiz.load_notes_dirs())

    def compose(self) -> ComposeResult:
        with Vertical(id="notes-dialog"):
            yield Static("QuizMe — study-notes folders", classes="title")
            yield Static(
                "QuizMe builds questions from every .md file under these folders.",
                classes="hint",
            )
            yield ListView(id="notes-list")
            with Horizontal(id="notes-add-row"):
                yield Input(placeholder="…or type / paste a folder path", id="notes-path")
                yield Button("Add path", id="notes-add-path")
            with Horizontal(id="notes-btns"):
                yield Button("Add folder…", id="notes-browse", variant="primary")
                yield Button("Remove", id="notes-remove", variant="error")
                yield Button("Reset", id="notes-reset")
                yield Button("Save", id="notes-save", variant="success")
                yield Button("Cancel", id="notes-cancel")

    def on_mount(self) -> None:
        if not folder_picker.available():
            browse = self.query_one("#notes-browse", Button)
            browse.disabled = True
            browse.tooltip = "No native folder picker available — type or paste a path below instead."
        self._ccd_rebuild()

    # ---- list rendering ------------------------------------------------- #

    def _ccd_rebuild(self) -> None:
        lv = self.query_one("#notes-list", ListView)
        lv.clear()
        if not self._ccd_dirs:
            lv.append(ListItem(Label("(none — QuizMe will use its default folder)")))
            return
        for d in self._ccd_dirs:
            missing = "" if d.exists() else "  · missing"
            lv.append(ListItem(Label(f"{d}{missing}")))

    def _ccd_add(self, paths: list[Path]) -> None:
        existing = {str(x) for x in self._ccd_dirs}
        added = False
        for p in paths:
            if str(p) not in existing:
                self._ccd_dirs.append(p)
                existing.add(str(p))
                added = True
        if added:
            self._ccd_rebuild()

    # ---- buttons / input ------------------------------------------------ #

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "notes-browse":
            self._ccd_browse()
        elif bid == "notes-add-path":
            self._ccd_add_typed()
        elif bid == "notes-remove":
            self._ccd_remove_selected()
        elif bid == "notes-reset":
            self._ccd_dirs = []
            self._ccd_rebuild()
        elif bid == "notes-save":
            quiz.save_notes_dirs(self._ccd_dirs)
            self.dismiss(True)
        elif bid == "notes-cancel":
            self.dismiss(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "notes-path":
            self._ccd_add_typed()

    def _ccd_add_typed(self) -> None:
        inp = self.query_one("#notes-path", Input)
        raw = inp.value.strip()
        # Strip surrounding single or double quotes so that a path pasted from
        # Windows Explorer (e.g. "C:\Users\…\Notes") resolves correctly.
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
            raw = raw[1:-1].strip()
        if raw:
            self._ccd_add([quiz.expand_dir(raw)])
            inp.value = ""

    def _ccd_remove_selected(self) -> None:
        idx = self.query_one("#notes-list", ListView).index
        if idx is not None and 0 <= idx < len(self._ccd_dirs):
            del self._ccd_dirs[idx]
            self._ccd_rebuild()

    # ---- native picker (worker thread) ---------------------------------- #

    def _ccd_browse(self) -> None:
        self.query_one("#notes-browse", Button).disabled = True
        self._ccd_pick_worker()

    @work(thread=True, exclusive=True, group="notes-pick")
    def _ccd_pick_worker(self) -> None:
        start = next((d for d in self._ccd_dirs if d.exists()), Path.home())
        try:
            picked = folder_picker.pick_directories(start)
        except folder_picker.PickerUnavailable as exc:
            self.app.call_from_thread(self._ccd_pick_done, [], str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface, never crash the UI
            self.app.call_from_thread(self._ccd_pick_done, [], f"Picker failed: {exc}")
            return
        self.app.call_from_thread(self._ccd_pick_done, picked, "")

    def _ccd_pick_done(self, picked: list[Path], err: str) -> None:
        self.query_one("#notes-browse", Button).disabled = not folder_picker.available()
        if err:
            self.notify(err, severity="warning")
        elif picked:
            self._ccd_add(picked)

    def action_cancel(self) -> None:
        self.dismiss(False)
