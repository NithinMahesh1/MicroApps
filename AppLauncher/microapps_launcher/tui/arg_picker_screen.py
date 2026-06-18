"""Modal that lets the user pick a launch-time argument (e.g. a ClaudePanes layout).

Dismisses with the chosen file's cwd-relative ``value`` (a string), or ``None``
when cancelled. ``_ma_*`` attribute names avoid colliding with Textual internals.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option

from microapps_launcher.arg_picker import ArgChoice


class ArgPickerScreen(ModalScreen[str | None]):
    """A single-choice list of files with Launch/Cancel actions."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, label: str, choices: list[ArgChoice]) -> None:
        super().__init__()
        self._ma_label = label
        self._ma_choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Label(self._ma_label, id="picker-title")
            yield OptionList(
                *(self._option(choice) for choice in self._ma_choices),
                id="picker-list",
            )
            with Horizontal(id="picker-actions"):
                yield Button("Launch", id="picker-launch", variant="success")
                yield Button("Cancel", id="picker-cancel")

    @staticmethod
    def _option(choice: ArgChoice) -> Option:
        text = choice.label
        if choice.description:
            text = f"{choice.label}  —  {choice.description}"
        return Option(text)

    def on_mount(self) -> None:
        self.query_one("#picker-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # Fires on Enter / click of a row.
        self.dismiss(self._ma_choices[event.option_index].value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-launch":
            index = self.query_one("#picker-list", OptionList).highlighted
            if index is None:
                return
            self.dismiss(self._ma_choices[index].value)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
