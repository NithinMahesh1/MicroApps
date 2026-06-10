"""Headless smoke test for the Textual UI.

Mounts the app, verifies the app-list screen composes, then pushes the config
editor screen (exercising descriptors, the secret field, and the list field).
Runnable both under pytest and standalone (``python tests/test_tui_smoke.py``).
Skipped under pytest when Textual is not installed.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from microapps_launcher import paths
from microapps_launcher.manifest import load_registry
from microapps_launcher.process_manager import ProcessManager


def _scenario() -> None:
    from microapps_launcher.tui.app import MicroAppsLauncher
    from microapps_launcher.tui.config_screen import ConfigScreen

    root = paths.find_repo_root(Path(__file__).resolve().parent)
    registry = load_registry(root)

    async def run() -> None:
        app = MicroAppsLauncher(registry, ProcessManager(), root)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.screen.__class__.__name__ == "AppListScreen"
            target = next(a for a in registry.apps if a.config_file)
            app.push_screen(ConfigScreen(target, root))
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ConfigScreen"

    asyncio.run(run())


def test_tui_smoke() -> None:
    if importlib.util.find_spec("textual") is None:
        import pytest

        pytest.skip("textual not installed")
    _scenario()


if __name__ == "__main__":
    _scenario()
    print("TUI smoke OK")
