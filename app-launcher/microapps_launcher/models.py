"""Data models for the MicroApps Launcher registry (``apps.json``).

These frozen dataclasses are the single source of truth for the manifest as
consumed by the launcher. The JSON uses camelCase keys; the models use
snake_case. JSON->model parsing lives here (``*.from_dict``) so the mapping is
defined in exactly one place. This module is pure stdlib and must never import
``textual`` or any third-party package.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Prepare:
    """One-time build/install step, skipped when ``sentinel`` exists."""

    cmd: tuple[str, ...]
    sentinel: str | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "Prepare | None":
        if not data:
            return None
        return cls(cmd=tuple(data["cmd"]), sentinel=data.get("sentinel"))


@dataclass(frozen=True)
class ArgPicker:
    """A launch-time argument the user picks from a set of files.

    Before launch the UI offers the files matched by ``glob`` (relative to the
    app's ``cwd``) and, optionally, ``user_glob`` (an absolute / ``~``-expanded
    glob for user files outside the repo), then appends the chosen file's path
    to ``cmd``.
    """

    glob: str
    label: str = "Choose an option"
    user_glob: str | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "ArgPicker | None":
        if not data:
            return None
        return cls(
            glob=data["glob"],
            label=data.get("label", "Choose an option"),
            user_glob=data.get("userGlob"),
        )


@dataclass(frozen=True)
class Launch:
    """The command used to start an app."""

    cmd: tuple[str, ...]
    arg_picker: ArgPicker | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Launch":
        return cls(
            cmd=tuple(data["cmd"]),
            arg_picker=ArgPicker.from_dict(data.get("argPicker")),
        )


@dataclass(frozen=True)
class Prerequisite:
    """A single prerequisite check, discriminated by ``type``.

    type in {"python","node","dotnet-sdk"} -> ``min_version`` set
    type == "binary"      -> ``name`` set
    type == "binary-any"  -> ``names`` set
    type == "os"          -> ``name`` set, ``min_version`` optional
    """

    type: str
    min_version: str | None = None
    name: str | None = None
    names: tuple[str, ...] | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Prerequisite":
        names = data.get("names")
        return cls(
            type=data["type"],
            min_version=data.get("minVersion"),
            name=data.get("name"),
            names=tuple(names) if names is not None else None,
        )


@dataclass(frozen=True)
class App:
    """A single registered micro-application."""

    id: str
    name: str
    description: str
    stack: str
    cwd: str
    launch: Launch
    launch_mode: str
    stoppable: bool
    prerequisites: tuple[Prerequisite, ...] = ()
    icon: str | None = None
    prepare: Prepare | None = None
    config_file: str | None = None
    config_template: str | None = None
    config_schema: str | None = None
    docs: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "App":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            stack=data["stack"],
            cwd=data["cwd"],
            launch=Launch.from_dict(data["launch"]),
            launch_mode=data["launchMode"],
            stoppable=data["stoppable"],
            prerequisites=tuple(
                Prerequisite.from_dict(p) for p in data.get("prerequisites", [])
            ),
            icon=data.get("icon"),
            prepare=Prepare.from_dict(data.get("prepare")),
            config_file=data.get("configFile"),
            config_template=data.get("configTemplate"),
            config_schema=data.get("configSchema"),
            docs=data.get("docs"),
        )


@dataclass(frozen=True)
class Registry:
    """The parsed ``apps.json`` document."""

    version: str
    apps: tuple[App, ...]

    @classmethod
    def from_dict(cls, data: dict) -> "Registry":
        return cls(
            version=data["version"],
            apps=tuple(App.from_dict(a) for a in data["apps"]),
        )

    def app(self, app_id: str) -> App | None:
        """Return the app with ``app_id`` or ``None``."""
        return next((a for a in self.apps if a.id == app_id), None)
