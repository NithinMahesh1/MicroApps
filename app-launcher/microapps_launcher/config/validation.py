"""Validate edited config values against their field descriptors."""
from __future__ import annotations

import re

from microapps_launcher.config.descriptors import FieldDescriptor, flatten

_CLIENT_ID_RE = re.compile(r"^\d+-.+\.apps\.googleusercontent\.com$")
_PLACEHOLDER_PREFIXES = ("YOUR_", "your-")


def validate(descriptors: list[FieldDescriptor], values: dict) -> dict[str, str]:
    """Return ``{dot_key: error_message}`` (empty == valid)."""
    flat = flatten(values)
    errors: dict[str, str] = {}

    for descriptor in descriptors:
        value = flat.get(descriptor.key)

        if descriptor.type == "string-list":
            items = [str(v).strip() for v in value] if isinstance(value, list) else []
            if descriptor.required and not any(items):
                errors[descriptor.key] = "At least one entry is required."
            continue

        text = "" if value is None else str(value)
        if descriptor.required and (not text.strip() or text.startswith(_PLACEHOLDER_PREFIXES)):
            errors[descriptor.key] = "Required — replace the placeholder with your value."
            continue

        if descriptor.key == "installed.client_id" and text and not _CLIENT_ID_RE.match(text):
            errors[descriptor.key] = "Expected <digits>-<...>.apps.googleusercontent.com"

    return errors
