"""Load and validate the ``apps.json`` registry into :class:`Registry`.

Pure stdlib, with optional stricter validation via ``jsonschema`` when it is
installed (a built-in fallback checker runs otherwise).
"""
from __future__ import annotations

import json
from pathlib import Path

from microapps_launcher.models import Registry


class ManifestError(Exception):
    """Raised when ``apps.json`` is missing, malformed, or fails validation."""


def load_schema(root: Path) -> dict:
    """Return the parsed ``apps.schema.json`` (or ``{}`` if it is absent)."""
    schema_path = root / "apps.schema.json"
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ManifestError(f"apps.schema.json is not valid JSON: {exc}") from exc


def validate(data: dict, schema: dict) -> list[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    if schema:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            pass
        else:
            validator = Draft202012Validator(schema)
            errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
            return [_format_error(e) for e in errors]
    return _fallback_validate(data)


def _format_error(error: object) -> str:
    path = "/".join(str(p) for p in getattr(error, "path", [])) or "(root)"
    return f"{path}: {getattr(error, 'message', error)}"


def _fallback_validate(data: dict) -> list[str]:
    """Minimal structural validation used when ``jsonschema`` is unavailable."""
    errors: list[str] = []
    if data.get("version") != "1":
        errors.append("version: must be the string '1'")
    apps = data.get("apps")
    if not isinstance(apps, list) or not apps:
        errors.append("apps: must be a non-empty array")
        return errors

    required = {
        "id", "name", "description", "stack", "cwd",
        "launch", "launchMode", "stoppable", "prerequisites",
    }
    stacks = {"python", "dotnet", "node", "binary"}
    modes = {"gui", "console", "fire-and-forget"}
    for index, app in enumerate(apps):
        where = f"apps[{index}]"
        if not isinstance(app, dict):
            errors.append(f"{where}: must be an object")
            continue
        for key in sorted(required - app.keys()):
            errors.append(f"{where}: missing required field '{key}'")
        if app.get("stack") not in stacks:
            errors.append(f"{where}.stack: invalid value {app.get('stack')!r}")
        if app.get("launchMode") not in modes:
            errors.append(f"{where}.launchMode: invalid value {app.get('launchMode')!r}")
        if app.get("launchMode") == "fire-and-forget" and app.get("stoppable") is not False:
            errors.append(f"{where}: fire-and-forget apps must have stoppable=false")
        launch = app.get("launch")
        if not isinstance(launch, dict) or not launch.get("cmd"):
            errors.append(f"{where}.launch.cmd: required non-empty array")
    return errors


def load_registry(root: Path) -> Registry:
    """Read, validate, and parse ``root/apps.json`` into a :class:`Registry`."""
    path = root / "apps.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ManifestError(f"apps.json not found at {path}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"apps.json is not valid JSON: {exc}") from exc

    errors = validate(data, load_schema(root))
    if errors:
        raise ManifestError(
            "apps.json failed validation:\n  - " + "\n  - ".join(errors)
        )

    try:
        return Registry.from_dict(data)
    except (KeyError, TypeError) as exc:
        raise ManifestError(f"apps.json could not be parsed: {exc}") from exc
