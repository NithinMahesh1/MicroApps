"""The main screen: list apps with live status and Launch/Stop/Config actions."""
from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, Static

from microapps_launcher import prepare, prerequisites
from microapps_launcher.models import App, Registry
from microapps_launcher.process_manager import ProcessManager
from microapps_launcher.tui.widgets import StatusBadge

try:
    import pyfiglet
except ImportError:  # pragma: no cover - banner is optional
    pyfiglet = None


class AppListScreen(Screen):
    """Lists every registered app with controls.

    ``_ma_*`` attribute names avoid colliding with Textual internals.
    """

    BINDINGS = [("r", "refresh", "Refresh"), ("q", "quit", "Quit")]

    def __init__(self, registry: Registry, pm: ProcessManager, repo_root: Path) -> None:
        super().__init__()
        self._ma_registry = registry
        self._ma_pm = pm
        self._ma_root = repo_root

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        if pyfiglet is not None:
            yield Static(pyfiglet.figlet_format("MicroApps", font="small"), classes="banner")
        with VerticalScroll(id="app-list"):
            for app in self._ma_registry.apps:
                yield from self._app_row(app)
        yield Footer()

    def _app_row(self, app: App) -> ComposeResult:
        icon = f"{app.icon} " if app.icon else ""
        with Horizontal(classes="app-row"):
            yield Label(f"{icon}{app.name}", classes="app-name")
            yield StatusBadge(id=f"status-{app.id}", classes="badge")
            yield Button("Launch", id=f"launch-{app.id}", variant="success")
            yield Button("Stop", id=f"stop-{app.id}", variant="error",
                         disabled=not app.stoppable)
            if app.config_file:
                yield Button("Config", id=f"config-{app.id}")

    def on_mount(self) -> None:
        self._refresh_statuses()

    def action_refresh(self) -> None:
        self._refresh_statuses()

    def _refresh_statuses(self) -> None:
        for app in self._ma_registry.apps:
            self.query_one(f"#status-{app.id}", StatusBadge).set_status(
                self._ma_pm.status(app.id)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        action, _, app_id = (event.button.id or "").partition("-")
        app = self._ma_registry.app(app_id)
        if app is None:
            return
        if action == "launch":
            self._launch(app)
        elif action == "stop":
            self._ma_pm.stop(app.id)
            self._refresh_statuses()
            self.notify(f"Stopped {app.name}.")
        elif action == "config":
            from microapps_launcher.tui.config_screen import ConfigScreen
            self.app.push_screen(ConfigScreen(app, self._ma_root))

    def _launch(self, app: App) -> None:
        failures = [r for r in prerequisites.check_all(app) if not r.ok]
        if failures:
            detail = "; ".join(f"{r.label}: {r.detail}" for r in failures)
            self.notify(f"Cannot launch {app.name} — {detail}",
                        severity="error", timeout=8)
            return
        if prepare.needs_prepare(self._ma_root, app):
            self.notify(f"Preparing {app.name} (first run, this can take a minute)…")
            self._prepare_then_launch(app)
        else:
            self._do_launch(app)

    @work(thread=True)
    def _prepare_then_launch(self, app: App) -> None:
        output: list[str] = []
        code = prepare.run_prepare(self._ma_root, app, on_line=output.append)
        self.app.call_from_thread(self._after_prepare, app, code, output)

    def _after_prepare(self, app: App, code: int, output: list[str]) -> None:
        if code != 0:
            tail = " ⏎ ".join(line for line in output[-3:] if line.strip()) or "no output"
            self.notify(f"Prepare failed for {app.name} (exit {code}): {tail}",
                        severity="error", timeout=12)
            return
        self._do_launch(app)

    def _do_launch(self, app: App) -> None:
        try:
            self._ma_pm.launch(self._ma_root, app)
        except OSError as exc:
            self.notify(f"Launch failed: {exc}", severity="error", timeout=8)
            return
        self._refresh_statuses()
        self.notify(f"Launched {app.name}.")
