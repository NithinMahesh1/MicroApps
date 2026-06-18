"""The Textual application shell."""
from __future__ import annotations

from pathlib import Path

from textual.app import App

from microapps_launcher import paths
from microapps_launcher.manifest import load_registry
from microapps_launcher.models import Registry
from microapps_launcher.process_manager import ProcessManager
from microapps_launcher.tui.app_list import AppListScreen


class MicroAppsLauncher(App):
    """Top-level launcher app.

    Instance attributes are ``_ma_*`` prefixed to avoid colliding with Textual's
    own internal ``App`` attributes (e.g. ``_registry``).
    """

    CSS_PATH = "app.tcss"
    TITLE = "MicroApps Launcher"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, registry: Registry, pm: ProcessManager, repo_root: Path) -> None:
        super().__init__()
        self._ma_registry = registry
        self._ma_pm = pm
        self._ma_root = repo_root

    def on_mount(self) -> None:
        self.push_screen(AppListScreen(self._ma_registry, self._ma_pm, self._ma_root))


def run_app() -> None:
    """Resolve the repo, load the manifest, and run the TUI.

    May raise :class:`~microapps_launcher.manifest.ManifestError` /
    ``FileNotFoundError`` (handled by the launcher entry point).
    """
    root = paths.find_repo_root(Path(__file__).resolve().parent)
    registry = load_registry(root)
    MicroAppsLauncher(registry, ProcessManager(), root).run()
