"""Reusable Textual widgets for the launcher UI."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static


class StatusBadge(Static):
    """A small running / stopped indicator."""

    def set_status(self, status: str) -> None:
        if status == "running":
            self.update("[green]● running[/]")
        else:
            self.update("[dim]○ stopped[/]")


class SecretInput(Horizontal):
    """A masked text field with a show/hide toggle button."""

    def __init__(self, value: str = "", placeholder: str = "", id: str | None = None) -> None:
        super().__init__(id=id)
        self._initial = value
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Input(value=self._initial, placeholder=self._placeholder, password=True)
        yield Button("show", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # Only our toggle button lives in here; keep it from reaching the screen.
        event.stop()
        field = self.query_one(Input)
        field.password = not field.password
        event.button.label = "show" if field.password else "hide"

    @property
    def value(self) -> str:
        return self.query_one(Input).value
