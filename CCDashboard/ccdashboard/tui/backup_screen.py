"""Backup modal — copy the whole ``~/.claude`` into a dated snapshot folder.

A :class:`~textual.screen.ModalScreen` over the Config tab (opened with Ctrl+B).
The directory field is masked by default (it can hold a private path) with a
``show``/``hide`` reveal toggle. The actual copy is delegated to the UI-agnostic
``ccdashboard.backup`` engine and runs in a ``@work(thread=True)`` worker so a
large ``~/.claude`` never freezes the terminal; every UI update from that worker
is marshalled back with ``self.app.call_from_thread(...)``.

Custom attrs/methods are ``_ccd_`` prefixed to avoid colliding with Textual's
``Screen`` internals.
"""
from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from ccdashboard import backup


class BackupScreen(ModalScreen):
    """Centered modal that backs up ``~/.claude`` to the chosen directory."""

    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, config_dir: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self._ccd_config_dir = config_dir
        self._ccd_busy = False

    def compose(self) -> ComposeResult:
        with Vertical(id="backup-dialog"):
            yield Static("◇ Back up ~/.claude", id="backup-title")
            yield Static(
                "Snapshots are written to a dated folder under this directory.",
                id="backup-hint",
                classes="status",
            )
            with Horizontal(id="backup-dir-row"):
                yield Input(id="backup-dir", password=True)
                yield Button("show", id="backup-reveal")
            with Horizontal(id="backup-actions"):
                yield Button("Back up now", id="backup-run", variant="primary")
                yield Button("Close", id="backup-close")
            yield Static("", id="backup-status", classes="status")

    def on_mount(self) -> None:
        field = self.query_one("#backup-dir", Input)
        field.value = backup.get_backup_dir()
        self.query_one("#backup-status", Static).update(
            "Copies your whole ~/.claude into a dated folder under this directory."
        )
        field.focus()

    # ---- button routing ------------------------------------------------- #

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "backup-reveal":
            field = self.query_one("#backup-dir", Input)
            field.password = not field.password
            event.button.label = "show" if field.password else "hide"
        elif button_id == "backup-close":
            self.dismiss()
        elif button_id == "backup-run":
            self._ccd_start_backup()

    # ---- backup kick-off + worker --------------------------------------- #

    def _ccd_start_backup(self) -> None:
        if self._ccd_busy:
            return
        value = self.query_one("#backup-dir", Input).value.strip()
        status = self.query_one("#backup-status", Static)
        if not value:
            status.update("Enter a backup directory.")
            return
        backup.set_backup_dir(value)
        self._ccd_busy = True
        self.query_one("#backup-run", Button).disabled = True
        status.update("Backing up… (this can take a while for a large ~/.claude)")
        self._ccd_backup_worker(value)

    @work(thread=True)
    def _ccd_backup_worker(self, backup_dir: str) -> None:
        """Run the copy off the UI thread; report back via ``call_from_thread``."""
        try:
            result = backup.backup_claude(self._ccd_config_dir, backup_dir)
            message = (
                f"Backed up {result['files']} files "
                f"({result['bytes'] / 1_048_576:.1f} MB) to {result['dest']}"
            )
            if result.get("skipped"):
                message += f"  ·  {result['skipped']} skipped"
        except Exception as exc:  # noqa: BLE001 — surface any failure, never crash
            message = f"Backup failed: {exc}"
        # We are on a worker thread: every UI mutation goes through the app.
        self.app.call_from_thread(self._ccd_finish, message)

    def _ccd_finish(self, message: str) -> None:
        """Re-enable the button, clear the busy flag and show the outcome (UI thread)."""
        self._ccd_busy = False
        try:
            self.query_one("#backup-run", Button).disabled = False
            self.query_one("#backup-status", Static).update(message)
        except NoMatches:
            # The modal was dismissed while the copy was still running; the backup
            # itself still completed — there's just no longer a UI to update.
            pass

    # ---- bindings ------------------------------------------------------- #

    def action_dismiss(self) -> None:
        self.dismiss()
