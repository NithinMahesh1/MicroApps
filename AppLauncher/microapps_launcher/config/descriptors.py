"""Build form-field descriptors for an app's config from its example template."""
from __future__ import annotations

import re
from dataclasses import dataclass

from microapps_launcher.models import App

_SECRET_HINTS = ("secret", "token", "password", "passwd")

# Per-app overrides keyed by dot-path. Anything not listed is inferred.
_OVERRIDES: dict[str, dict[str, dict]] = {
    "meeting-tracker": {
        "installed.client_id": {"required": True,
                                "help": "OAuth Desktop client ID from Google Cloud Console."},
        "installed.client_secret": {"required": True, "secret": True, "type": "secret"},
        "installed.project_id": {"required": True},
    },
    "meeting-notes-overlay": {
        "notesDirectories": {"type": "string-list", "required": True,
                             "help": "Folders scanned for .txt/.md notes (%USERPROFILE% expands)."},
    },
}


@dataclass(frozen=True)
class FieldDescriptor:
    key: str
    label: str
    type: str  # text | secret | string-list | file-path | readonly
    secret: bool = False
    required: bool = False
    help: str = ""
    placeholder: str = ""


def flatten(data: dict, prefix: str = "") -> dict[str, object]:
    """Flatten nested dicts to dot-path keys (lists are kept as leaf values)."""
    out: dict[str, object] = {}
    for key, value in (data or {}).items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(flatten(value, path))
        else:
            out[path] = value
    return out


def unflatten(flat: dict[str, object]) -> dict:
    """Inverse of :func:`flatten`."""
    root: dict = {}
    for key, value in flat.items():
        parts = key.split(".")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return root


def _humanize(key: str) -> str:
    segment = key.split(".")[-1].replace("_", " ").replace("-", " ")
    segment = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", segment)  # camelCase -> words
    return segment[:1].upper() + segment[1:]


def descriptors_for(app: App, example: dict) -> list[FieldDescriptor]:
    """Infer field descriptors from *example* (the template JSON), then apply
    per-app overrides."""
    overrides = _OVERRIDES.get(app.id, {})
    descriptors: list[FieldDescriptor] = []
    for key, value in flatten(example).items():
        inferred_type = "string-list" if isinstance(value, list) else "text"
        secret = any(hint in key.lower() for hint in _SECRET_HINTS)
        if secret:
            inferred_type = "secret"
        override = overrides.get(key, {})
        descriptors.append(
            FieldDescriptor(
                key=key,
                label=_humanize(key),
                type=override.get("type", inferred_type),
                secret=override.get("secret", secret),
                required=override.get("required", False),
                help=override.get("help", ""),
                placeholder="" if isinstance(value, list) else str(value),
            )
        )
    return descriptors
