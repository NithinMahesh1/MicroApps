"""Edit an app's config. Writes only the git-ignored real file."""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, TextArea

from microapps_launcher.config import io, validation
from microapps_launcher.config.descriptors import (
    FieldDescriptor,
    descriptors_for,
    flatten,
    unflatten,
)
from microapps_launcher.models import App
from microapps_launcher.tui.widgets import SecretInput


def _field_id(key: str) -> str:
    return "f_" + key.replace(".", "__").replace("-", "_")


class ConfigScreen(Screen):
    """A simple form generated from the app's config template.

    ``_ma_*`` attribute names avoid colliding with Textual internals.
    """

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, app_def: App, repo_root: Path) -> None:
        super().__init__()
        self._ma_app = app_def
        self._ma_root = repo_root
        self._ma_descriptors: list[FieldDescriptor] = []
        self._ma_values: dict[str, object] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        template = io.load_template(self._ma_root, self._ma_app)
        self._ma_descriptors = descriptors_for(self._ma_app, template)
        self._ma_values = flatten(io.load_values(self._ma_root, self._ma_app))
        with VerticalScroll(id="config-form"):
            yield Static(
                f"Editing [b]{self._ma_app.name}[/b]  →  {self._ma_app.config_file}",
                classes="config-title",
            )
            for descriptor in self._ma_descriptors:
                yield Label(("* " if descriptor.required else "") + descriptor.label,
                            classes="field-label")
                if descriptor.help:
                    yield Static(descriptor.help, classes="field-help")
                yield from self._field_widget(descriptor)
            yield Static("", id="errors", classes="errors")
            with Horizontal(classes="actions"):
                yield Button("Save", id="save", variant="success")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def _field_widget(self, descriptor: FieldDescriptor) -> ComposeResult:
        current = self._ma_values.get(descriptor.key)
        widget_id = _field_id(descriptor.key)
        if descriptor.type == "secret":
            yield SecretInput(value="" if current is None else str(current),
                              placeholder=descriptor.placeholder, id=widget_id)
        elif descriptor.type == "string-list":
            text = "\n".join(current) if isinstance(current, list) else ""
            yield TextArea(text, id=widget_id, classes="list-field")
        else:
            yield Input(value="" if current is None else str(current),
                        placeholder=descriptor.placeholder, id=widget_id)

    def _collect(self) -> dict:
        flat: dict[str, object] = {}
        for descriptor in self._ma_descriptors:
            widget = self.query_one(f"#{_field_id(descriptor.key)}")
            if descriptor.type == "string-list":
                flat[descriptor.key] = [
                    line.strip() for line in widget.text.splitlines() if line.strip()
                ]
            else:
                flat[descriptor.key] = widget.value
        return unflatten(flat)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.app.pop_screen()
        elif event.button.id == "save":
            self._save()

    def _save(self) -> None:
        values = self._collect()
        errors = validation.validate(self._ma_descriptors, values)
        errors_widget = self.query_one("#errors", Static)
        if errors:
            lines = "\n".join(f"• {self._label(k)}: {msg}" for k, msg in errors.items())
            errors_widget.update(f"[red]{lines}[/]")
            return
        path = io.save_values(self._ma_root, self._ma_app, values)
        errors_widget.update(f"[green]Saved → {path}[/]")
        self.notify("Config saved.")

    def _label(self, key: str) -> str:
        return next((d.label for d in self._ma_descriptors if d.key == key), key)
