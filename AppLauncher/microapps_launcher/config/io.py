"""Load and save app config values. Writes only the git-ignored real file."""
from __future__ import annotations

import json
import os
from pathlib import Path

from microapps_launcher import paths
from microapps_launcher.models import App

_PLACEHOLDER_PREFIXES = ("YOUR_", "your-")


def _strip_placeholders(data: object) -> object:
    if isinstance(data, dict):
        return {k: _strip_placeholders(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_strip_placeholders(v) for v in data]
    if isinstance(data, str) and data.startswith(_PLACEHOLDER_PREFIXES):
        return ""
    return data


def load_template(root: Path, app: App) -> dict:
    """Return the parsed ``configTemplate`` (defines the form shape), or ``{}``."""
    if not app.config_template:
        return {}
    path = paths.resolve_repo(root, app.config_template)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_values(root: Path, app: App) -> dict:
    """Return current config values: the real file if present, else the template
    with placeholder sentinels stripped to empty."""
    if app.config_file:
        real = paths.resolve_repo(root, app.config_file)
        if real.exists():
            return json.loads(real.read_text(encoding="utf-8"))
    template = load_template(root, app)
    return _strip_placeholders(template) if template else {}


def save_values(root: Path, app: App, values: dict) -> Path:
    """Write *values* to the app's (git-ignored) real config file, pretty-printed.

    Raises ``ValueError`` if the app has no ``configFile``.
    """
    if not app.config_file:
        raise ValueError(f"{app.id} has no configFile to write to")
    real = paths.resolve_repo(root, app.config_file)
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    return real


def expand_preview(value: str) -> str:
    """Expand environment variables (``%USERPROFILE%`` etc.) for display only."""
    return os.path.expandvars(value)
